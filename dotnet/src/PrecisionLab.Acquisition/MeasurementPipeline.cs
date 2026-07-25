using System.Threading.Channels;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Domain;
using PrecisionLab.Storage;

namespace PrecisionLab.Acquisition;

public interface IMeasurementPublisher
{
    ValueTask PublishAsync(
        Guid sessionId,
        Measurement measurement,
        CancellationToken cancellationToken);

    async ValueTask PublishBatchAsync(
        Guid sessionId,
        IReadOnlyList<Measurement> measurements,
        CancellationToken cancellationToken)
    {
        foreach (Measurement measurement in measurements)
        {
            await PublishAsync(
                sessionId,
                measurement,
                cancellationToken).ConfigureAwait(false);
        }
    }
}

public sealed partial class MeasurementPipeline : BackgroundService, IMeasurementPublisher
{
    private readonly Channel<PendingMeasurement> _ingress;
    private readonly ISessionStore _store;
    private readonly MeasurementHub _hub;
    private readonly ILogger<MeasurementPipeline> _logger;

    public MeasurementPipeline(
        ISessionStore store,
        MeasurementHub hub,
        ILogger<MeasurementPipeline> logger,
        int capacity = 4_096)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(capacity);
        _store = store;
        _hub = hub;
        _logger = logger;
        _ingress = Channel.CreateBounded<PendingMeasurement>(
            new BoundedChannelOptions(capacity)
            {
                FullMode = BoundedChannelFullMode.Wait,
                SingleReader = true,
                SingleWriter = false,
                AllowSynchronousContinuations = false,
            });
    }

    public async ValueTask PublishAsync(
        Guid sessionId,
        Measurement measurement,
        CancellationToken cancellationToken) =>
        await PublishBatchAsync(
            sessionId,
            [measurement],
            cancellationToken).ConfigureAwait(false);

    public async ValueTask PublishBatchAsync(
        Guid sessionId,
        IReadOnlyList<Measurement> measurements,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(measurements);
        if (measurements.Count == 0)
        {
            return;
        }

        var completion = new TaskCompletionSource(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var pending = new PendingMeasurement(sessionId, measurements, completion);
        await _ingress.Writer.WriteAsync(pending, cancellationToken).ConfigureAwait(false);
        await completion.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        Exception? failure = null;
        try
        {
            await _store.InitializeAsync(stoppingToken).ConfigureAwait(false);
            await foreach (PendingMeasurement pending in
                           _ingress.Reader.ReadAllAsync(CancellationToken.None))
            {
                try
                {
                    await _store.AppendBatchAsync(
                        pending.SessionId,
                        pending.Measurements,
                        CancellationToken.None).ConfigureAwait(false);
                    foreach (Measurement measurement in pending.Measurements)
                    {
                        _hub.Publish(measurement);
                    }

                    pending.Completion.TrySetResult();
                }
                catch (Exception exception)
                {
                    pending.Completion.TrySetException(exception);
                    failure = exception;
                    _ingress.Writer.TryComplete(exception);
                    throw;
                }
            }
        }
        catch (Exception exception)
        {
            failure = exception;
            LogPipelineStopped(_logger, exception);
            throw;
        }
        finally
        {
            while (_ingress.Reader.TryRead(out PendingMeasurement? pending))
            {
                pending.Completion.TrySetException(
                    failure ?? new InvalidOperationException(
                        "The durable measurement pipeline stopped."));
            }

            _hub.Complete();
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _ingress.Writer.TryComplete();
        await base.StopAsync(cancellationToken).ConfigureAwait(false);
    }

    [LoggerMessage(
        EventId = 20,
        Level = LogLevel.Critical,
        Message = "The durable measurement pipeline stopped unexpectedly.")]
    private static partial void LogPipelineStopped(
        ILogger logger,
        Exception exception);

    private sealed record PendingMeasurement(
        Guid SessionId,
        IReadOnlyList<Measurement> Measurements,
        TaskCompletionSource Completion);
}
