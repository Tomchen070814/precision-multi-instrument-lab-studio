using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Acquisition;

public sealed class AcquisitionCoordinator : IHostedService
{
    private readonly IReadOnlyDictionary<ChannelId, ChannelRuntime> _channels;
    private readonly Dictionary<ChannelId, AcquisitionSettings> _settings;
    private readonly SemaphoreSlim _operationLock = new(1, 1);

    public AcquisitionCoordinator(
        IInstrumentDriverFactory driverFactory,
        IMeasurementPublisher publisher,
        ILogger<AcquisitionCoordinator> logger)
    {
        ArgumentNullException.ThrowIfNull(driverFactory);
        ArgumentNullException.ThrowIfNull(publisher);
        ServiceStartedUtc = DateTimeOffset.UtcNow;
        _settings = new Dictionary<ChannelId, AcquisitionSettings>
        {
            [ChannelId.A] = DefaultSettings(
                InstrumentModel.Keysight3458A,
                "SIM::3458A",
                TimeSpan.FromMilliseconds(100)),
            [ChannelId.B] = DefaultSettings(
                InstrumentModel.Keysight34470A,
                "SIM::34470A",
                TimeSpan.FromMilliseconds(125)),
            [ChannelId.C] = DefaultSettings(
                InstrumentModel.Fluke8508A,
                "SIM::8508A",
                TimeSpan.FromMilliseconds(150)),
        };
        _channels = Enum.GetValues<ChannelId>().ToDictionary(
            id => id,
            id => new ChannelRuntime(id, _settings[id], driverFactory, publisher, logger));
    }

    public DateTimeOffset ServiceStartedUtc { get; }

    public Task StartAsync(CancellationToken cancellationToken) => Task.CompletedTask;

    public async Task StartChannelsAsync(
        IEnumerable<ChannelId> channels,
        IReadOnlyDictionary<ChannelId, AcquisitionSettings>? settings,
        CancellationToken cancellationToken)
    {
        ChannelId[] selected = channels.Distinct().ToArray();
        if (selected.Length == 0)
        {
            throw new ArgumentException("Select at least one channel.", nameof(channels));
        }

        await _operationLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            foreach (ChannelId channel in selected)
            {
                if (settings?.TryGetValue(channel, out AcquisitionSettings? configured) == true)
                {
                    _settings[channel] = configured.Validate();
                }
            }

            var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            try
            {
                await Task.WhenAll(
                    selected.Select(
                        channel => _channels[channel].PrepareAsync(
                            _settings[channel],
                            release.Task,
                            cancellationToken))).ConfigureAwait(false);
                release.SetResult();
            }
            catch
            {
                release.TrySetCanceled(cancellationToken);
                await Task.WhenAll(
                    selected.Select(channel => SafeStopAsync(channel))).ConfigureAwait(false);
                throw;
            }
        }
        finally
        {
            _operationLock.Release();
        }
    }

    public async Task StopChannelsAsync(
        IEnumerable<ChannelId> channels,
        CancellationToken cancellationToken)
    {
        ChannelId[] selected = channels.Distinct().ToArray();
        await _operationLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await Task.WhenAll(
                selected.Select(
                    channel => _channels[channel].StopAsync(cancellationToken))).ConfigureAwait(false);
        }
        finally
        {
            _operationLock.Release();
        }
    }

    public ServiceSnapshot Snapshot() =>
        new(
            ProtocolVersion: 1,
            ServiceVersion: "0.1.0-phase1",
            ServiceStartedUtc,
            Environment.ProcessId,
            Environment.WorkingSet,
            Enum.GetValues<ChannelId>().Select(channel => _channels[channel].Snapshot()).ToArray());

    public Task StopAsync(CancellationToken cancellationToken) =>
        StopChannelsAsync(Enum.GetValues<ChannelId>(), cancellationToken);

    private static AcquisitionSettings DefaultSettings(
        InstrumentModel model,
        string resource,
        TimeSpan interval) =>
        new()
        {
            InstrumentModel = model,
            Resource = resource,
            Function = MeasurementFunction.DcVoltage,
            SampleInterval = interval,
            Nplc = 10,
            Digits = 8,
            Autozero = "ON",
        };

    private async Task SafeStopAsync(ChannelId channel)
    {
        try
        {
            await _channels[channel].StopAsync(CancellationToken.None).ConfigureAwait(false);
        }
        catch
        {
            // Preserve the original prepare failure.
        }
    }
}
