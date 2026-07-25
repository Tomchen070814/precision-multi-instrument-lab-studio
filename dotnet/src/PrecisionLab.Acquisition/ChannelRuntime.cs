using System.Diagnostics;
using Microsoft.Extensions.Logging;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;
using PrecisionLab.Storage;

namespace PrecisionLab.Acquisition;

internal sealed partial class ChannelRuntime
{
    private readonly object _sync = new();
    private readonly IInstrumentDriverFactory _driverFactory;
    private readonly IMeasurementPublisher _publisher;
    private readonly ISessionStore _store;
    private readonly ILogger _logger;
    private CancellationTokenSource? _runCancellation;
    private Task? _runTask;
    private ChannelState _state = ChannelState.Stopped;
    private AcquisitionSettings _settings;
    private InstrumentIdentity? _identity;
    private Guid? _sessionId;
    private long _sampleCount;
    private long _committedSamples;
    private double? _lastValue;
    private DateTimeOffset? _startedUtc;
    private string? _error;

    public ChannelRuntime(
        ChannelId channel,
        AcquisitionSettings settings,
        IInstrumentDriverFactory driverFactory,
        IMeasurementPublisher publisher,
        ISessionStore store,
        ILogger logger)
    {
        Channel = channel;
        _settings = settings.Validate();
        _driverFactory = driverFactory;
        _publisher = publisher;
        _store = store;
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
            _sessionId = null;
            _sampleCount = 0;
            _committedSamples = 0;
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
            bool nativeBurst =
                settings.Function is
                    MeasurementFunction.DigitizeDc or MeasurementFunction.DigitizeAc &&
                driver is IBurstInstrumentDriver;
            if (!nativeBurst)
            {
                await driver.ConfigureAsync(settings, cancellationToken).ConfigureAwait(false);
            }

            var runCancellation = new CancellationTokenSource();
            lock (_sync)
            {
                _identity = identity;
                _runCancellation = runCancellation;
                _state = ChannelState.Armed;
                _runTask = Task.Run(
                    () => RunLoopAsync(
                        driver,
                        identity,
                        settings,
                        releaseSignal,
                        runCancellation.Token),
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
            if (_state != ChannelState.Faulted)
            {
                _state = ChannelState.Stopped;
            }

            _runCancellation?.Dispose();
            _runCancellation = null;
            _runTask = null;
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
                _error,
                _sessionId,
                _committedSamples);
        }
    }

    private async Task RunLoopAsync(
        IInstrumentDriver driver,
        InstrumentIdentity identity,
        AcquisitionSettings settings,
        Task releaseSignal,
        CancellationToken cancellationToken)
    {
        Guid? sessionId = null;
        SessionCompletionStatus completionStatus = SessionCompletionStatus.Completed;
        string? completionError = null;
        try
        {
            await releaseSignal.WaitAsync(cancellationToken).ConfigureAwait(false);
            DateTimeOffset startedUtc = DateTimeOffset.UtcNow;
            sessionId = await _store.BeginSessionAsync(
                Channel,
                settings,
                identity,
                startedUtc,
                cancellationToken).ConfigureAwait(false);
            var stopwatch = Stopwatch.StartNew();
            lock (_sync)
            {
                _state = ChannelState.Running;
                _startedUtc = startedUtc;
                _sessionId = sessionId;
            }

            if (settings.Function is
                    MeasurementFunction.DigitizeDc or MeasurementFunction.DigitizeAc &&
                driver is IBurstInstrumentDriver burstDriver &&
                settings.MaxSamples is long burstCount)
            {
                IReadOnlyList<Measurement> burst =
                    await burstDriver.AcquireBurstAsync(
                        Channel,
                        0,
                        new BurstAcquisitionSettings(
                            checked((int)burstCount),
                            settings.SampleInterval,
                            settings.BurstAperture,
                            settings.Function,
                            settings.MeasurementRange),
                        cancellationToken).ConfigureAwait(false);
                int persistenceBlockSize = settings.Durability switch
                {
                    StorageDurability.Maximum => 1,
                    StorageDurability.Balanced => 256,
                    StorageDurability.Throughput => 1_024,
                    _ => throw new ArgumentOutOfRangeException(nameof(settings)),
                };
                for (int offset = 0; offset < burst.Count; offset += persistenceBlockSize)
                {
                    Measurement[] block = burst
                        .Skip(offset)
                        .Take(persistenceBlockSize)
                        .ToArray();
                    Measurement measurement = block[^1];
                    lock (_sync)
                    {
                        _sampleCount = measurement.Sequence + 1;
                        _lastValue = measurement.Value;
                    }

                    await _publisher.PublishBatchAsync(
                        sessionId.Value,
                        block,
                        cancellationToken).ConfigureAwait(false);
                    lock (_sync)
                    {
                        _committedSamples = measurement.Sequence + 1;
                    }
                }

                return;
            }

            long sequence = 0;
            TimeSpan nextTemperature = TimeSpan.Zero;
            while (!cancellationToken.IsCancellationRequested)
            {
                TimeSpan elapsed = stopwatch.Elapsed;
                bool includeTemperature =
                    settings.IncludeTemperature && elapsed >= nextTemperature;
                Measurement measurement = await driver.ReadAsync(
                    Channel,
                    sequence,
                    elapsed,
                    includeTemperature,
                    cancellationToken).ConfigureAwait(false);
                lock (_sync)
                {
                    _sampleCount = sequence + 1;
                    _lastValue = measurement.Value;
                }

                await _publisher.PublishAsync(
                    sessionId.Value,
                    measurement,
                    cancellationToken).ConfigureAwait(false);

                sequence++;
                lock (_sync)
                {
                    _committedSamples = sequence;
                }

                if (includeTemperature)
                {
                    nextTemperature = elapsed + TimeSpan.FromSeconds(15);
                }

                if (settings.MaxSamples is long limit && sequence >= limit)
                {
                    break;
                }

                TimeSpan nextDue = TimeSpan.FromTicks(
                    checked(settings.SampleInterval.Ticks * sequence));
                TimeSpan remaining = nextDue - stopwatch.Elapsed;
                if (remaining > TimeSpan.Zero)
                {
                    await Task.Delay(remaining, cancellationToken).ConfigureAwait(false);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            completionStatus = SessionCompletionStatus.Stopped;
            LogChannelStopped(_logger, Channel);
        }
        catch (Exception exception)
        {
            completionStatus = SessionCompletionStatus.Faulted;
            completionError = exception.Message;
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
                if (sessionId is Guid completedSession)
                {
                    try
                    {
                        await _store.CompleteSessionAsync(
                            completedSession,
                            completionStatus,
                            completionError,
                            CancellationToken.None).ConfigureAwait(false);
                    }
                    catch (Exception exception)
                    {
                        SetFault(exception);
                        LogSessionFinalizeFailed(_logger, Channel, exception);
                    }
                }

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

    [LoggerMessage(
        EventId = 12,
        Level = LogLevel.Critical,
        Message = "Channel {Channel} session finalization failed.")]
    private static partial void LogSessionFinalizeFailed(
        ILogger logger,
        ChannelId channel,
        Exception exception);
}
