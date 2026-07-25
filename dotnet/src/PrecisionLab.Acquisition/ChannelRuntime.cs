using System.Diagnostics;
using Microsoft.Extensions.Logging;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Acquisition;

internal sealed partial class ChannelRuntime
{
    private readonly object _sync = new();
    private readonly IInstrumentDriverFactory _driverFactory;
    private readonly IMeasurementPublisher _publisher;
    private readonly ILogger _logger;
    private CancellationTokenSource? _runCancellation;
    private Task? _runTask;
    private ChannelState _state = ChannelState.Stopped;
    private AcquisitionSettings _settings;
    private InstrumentIdentity? _identity;
    private long _sampleCount;
    private double? _lastValue;
    private DateTimeOffset? _startedUtc;
    private string? _error;

    public ChannelRuntime(
        ChannelId channel,
        AcquisitionSettings settings,
        IInstrumentDriverFactory driverFactory,
        IMeasurementPublisher publisher,
        ILogger logger)
    {
        Channel = channel;
        _settings = settings.Validate();
        _driverFactory = driverFactory;
        _publisher = publisher;
        _logger = logger;
    }

    public ChannelId Channel { get; }

    public async Task PrepareAsync(
        AcquisitionSettings settings,
        Task releaseSignal,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(settings);
        settings.Validate();

        lock (_sync)
        {
            if (_state is not (ChannelState.Stopped or ChannelState.Faulted))
            {
                throw new InvalidOperationException($"Channel {Channel} is already {_state}.");
            }

            _state = ChannelState.Connecting;
            _settings = settings;
            _identity = null;
            _sampleCount = 0;
            _lastValue = null;
            _startedUtc = null;
            _error = null;
        }

        IInstrumentDriver driver = _driverFactory.Create(Channel, settings);
        try
        {
            InstrumentIdentity identity = await driver
                .ConnectAsync(cancellationToken)
                .ConfigureAwait(false);
            await driver.ConfigureAsync(settings, cancellationToken).ConfigureAwait(false);

            var runCancellation = new CancellationTokenSource();
            lock (_sync)
            {
                _identity = identity;
                _runCancellation = runCancellation;
                _state = ChannelState.Armed;
                _runTask = Task.Run(
                    () => RunLoopAsync(driver, settings, releaseSignal, runCancellation.Token),
                    CancellationToken.None);
            }
        }
        catch (Exception exception)
        {
            await driver.DisposeAsync().ConfigureAwait(false);
            SetFault(exception);
            throw;
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        CancellationTokenSource? runCancellation;
        Task? runTask;
        lock (_sync)
        {
            if (_state == ChannelState.Stopped)
            {
                return;
            }

            if (_state != ChannelState.Faulted)
            {
                _state = ChannelState.Stopping;
            }

            runCancellation = _runCancellation;
            runTask = _runTask;
        }

        runCancellation?.Cancel();
        if (runTask is not null)
        {
            await runTask.WaitAsync(cancellationToken).ConfigureAwait(false);
        }

        lock (_sync)
        {
            _state = ChannelState.Stopped;
            _runCancellation?.Dispose();
            _runCancellation = null;
            _runTask = null;
            _startedUtc = null;
        }
    }

    public ChannelSnapshot Snapshot()
    {
        lock (_sync)
        {
            return new ChannelSnapshot(
                Channel,
                _state,
                _settings.InstrumentModel,
                _settings.Function,
                _settings.Resource,
                _identity?.ReportedModel ?? string.Empty,
                _sampleCount,
                _lastValue,
                _settings.Function.Unit(),
                _startedUtc,
                _error);
        }
    }

    private async Task RunLoopAsync(
        IInstrumentDriver driver,
        AcquisitionSettings settings,
        Task releaseSignal,
        CancellationToken cancellationToken)
    {
        try
        {
            await releaseSignal.WaitAsync(cancellationToken).ConfigureAwait(false);
            DateTimeOffset startedUtc = DateTimeOffset.UtcNow;
            var stopwatch = Stopwatch.StartNew();
            lock (_sync)
            {
                _state = ChannelState.Running;
                _startedUtc = startedUtc;
            }

            long sequence = 0;
            TimeSpan nextTemperature = TimeSpan.Zero;
            while (!cancellationToken.IsCancellationRequested)
            {
                TimeSpan elapsed = stopwatch.Elapsed;
                bool includeTemperature = elapsed >= nextTemperature;
                Measurement measurement = await driver.ReadAsync(
                    Channel,
                    sequence,
                    elapsed,
                    includeTemperature,
                    cancellationToken).ConfigureAwait(false);
                await _publisher.PublishAsync(measurement, cancellationToken).ConfigureAwait(false);

                sequence++;
                lock (_sync)
                {
                    _sampleCount = sequence;
                    _lastValue = measurement.Value;
                }

                if (includeTemperature)
                {
                    nextTemperature = elapsed + TimeSpan.FromSeconds(15);
                }

                if (settings.MaxSamples is long limit && sequence >= limit)
                {
                    break;
                }

                TimeSpan nextDue = TimeSpan.FromSeconds(
                    settings.SampleInterval.TotalSeconds * sequence);
                TimeSpan remaining = nextDue - stopwatch.Elapsed;
                if (remaining > TimeSpan.Zero)
                {
                    await Task.Delay(remaining, cancellationToken).ConfigureAwait(false);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            LogChannelStopped(_logger, Channel);
        }
        catch (Exception exception)
        {
            SetFault(exception);
            LogChannelFailed(_logger, Channel, exception);
        }
        finally
        {
            try
            {
                await driver.DisconnectAsync(CancellationToken.None).ConfigureAwait(false);
            }
            finally
            {
                await driver.DisposeAsync().ConfigureAwait(false);
                lock (_sync)
                {
                    if (_state != ChannelState.Faulted)
                    {
                        _state = ChannelState.Stopped;
                    }
                }
            }
        }
    }

    private void SetFault(Exception exception)
    {
        lock (_sync)
        {
            _state = ChannelState.Faulted;
            _error = exception.Message;
        }
    }

    [LoggerMessage(
        EventId = 10,
        Level = LogLevel.Information,
        Message = "Channel {Channel} acquisition stopped.")]
    private static partial void LogChannelStopped(ILogger logger, ChannelId channel);

    [LoggerMessage(
        EventId = 11,
        Level = LogLevel.Error,
        Message = "Channel {Channel} acquisition failed.")]
    private static partial void LogChannelFailed(
        ILogger logger,
        ChannelId channel,
        Exception exception);
}
