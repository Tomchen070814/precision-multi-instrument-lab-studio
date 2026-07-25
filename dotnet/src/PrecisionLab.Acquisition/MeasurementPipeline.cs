using System.Threading.Channels;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Domain;

namespace PrecisionLab.Acquisition;

public interface IMeasurementPublisher
{
    ValueTask PublishAsync(Measurement measurement, CancellationToken cancellationToken);
}

public interface IMeasurementSink : IAsyncDisposable
{
    ValueTask WriteAsync(Measurement measurement, CancellationToken cancellationToken);

    ValueTask FlushAsync(CancellationToken cancellationToken);
}

public sealed partial class MeasurementPipeline : BackgroundService, IMeasurementPublisher
{
    private readonly Channel<Measurement> _ingress;
    private readonly IMeasurementSink _sink;
    private readonly MeasurementHub _hub;
    private readonly ILogger<MeasurementPipeline> _logger;

    public MeasurementPipeline(
        IMeasurementSink sink,
        MeasurementHub hub,
        ILogger<MeasurementPipeline> logger,
        int capacity = 4_096)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(capacity);
        _sink = sink;
        _hub = hub;
        _logger = logger;
        _ingress = Channel.CreateBounded<Measurement>(
            new BoundedChannelOptions(capacity)
            {
                FullMode = BoundedChannelFullMode.Wait,
                SingleReader = true,
                SingleWriter = false,
                AllowSynchronousContinuations = false,
            });
    }

    public ValueTask PublishAsync(
        Measurement measurement,
        CancellationToken cancellationToken) =>
        _ingress.Writer.WriteAsync(measurement, cancellationToken);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        try
        {
            // StopAsync completes the writer so this loop drains every accepted sample.
            await foreach (Measurement measurement in
                           _ingress.Reader.ReadAllAsync(CancellationToken.None))
            {
                await _sink.WriteAsync(
                    measurement,
                    CancellationToken.None).ConfigureAwait(false);
                await _sink.FlushAsync(CancellationToken.None).ConfigureAwait(false);

                // The display never sees a sample until its durable flush succeeds.
                _hub.Publish(measurement);
            }
        }
        catch (Exception exception)
        {
            LogPipelineStopped(_logger, exception);
            throw;
        }
        finally
        {
            await _sink.FlushAsync(CancellationToken.None).ConfigureAwait(false);
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
}
