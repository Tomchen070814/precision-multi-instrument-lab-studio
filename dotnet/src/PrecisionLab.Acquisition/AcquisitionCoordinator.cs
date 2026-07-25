using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;
using PrecisionLab.Storage;

namespace PrecisionLab.Acquisition;

public sealed class AcquisitionCoordinator : IHostedService, IDisposable
{
    private readonly Dictionary<ChannelId, ChannelRuntime> _channels;
    private readonly Dictionary<ChannelId, AcquisitionSettings> _settings;
    private readonly SemaphoreSlim _operationLock = new(1, 1);

    public AcquisitionCoordinator(
        IInstrumentDriverFactory driverFactory,
        IMeasurementPublisher publisher,
        ISessionStore store,
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
            id => new ChannelRuntime(
                id,
                _settings[id],
                driverFactory,
                publisher,
                store,
                logger));
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
                if (settings is not null &&
                    settings.TryGetValue(channel, out AcquisitionSettings? configured) &&
                    configured is not null)
                {
                    _settings[channel] = configured.Validate();
                }
            }

            EnsureUniquePhysicalResources(selected);

            var release = new TaskCompletionSource(
                TaskCreationOptions.RunContinuationsAsynchronously);
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
            ServiceVersion: "0.6.0-beta.1",
            ServiceStartedUtc: ServiceStartedUtc,
            ServiceProcessId: Environment.ProcessId,
            ServiceWorkingSetBytes: Environment.WorkingSet,
            Channels: Enum.GetValues<ChannelId>()
                .Select(channel => _channels[channel].Snapshot())
                .ToArray());

    public Task StopAsync(CancellationToken cancellationToken) =>
        StopChannelsAsync(Enum.GetValues<ChannelId>(), cancellationToken);

    public void Dispose() => _operationLock.Dispose();

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

    private void EnsureUniquePhysicalResources(IReadOnlyCollection<ChannelId> selected)
    {
        var resources = new List<(ChannelId Channel, string Resource)>();
        foreach (ChannelId channel in Enum.GetValues<ChannelId>())
        {
            ChannelSnapshot snapshot = _channels[channel].Snapshot();
            bool active = snapshot.State is not (
                ChannelState.Stopped or ChannelState.Faulted);
            if (!selected.Contains(channel) && !active)
            {
                continue;
            }

            string resource = _settings[channel].Resource.Trim();
            if (!resource.StartsWith("SIM::", StringComparison.OrdinalIgnoreCase))
            {
                resources.Add((channel, resource.ToUpperInvariant()));
            }
        }

        IGrouping<string, (ChannelId Channel, string Resource)>? duplicate =
            resources.GroupBy(item => item.Resource).FirstOrDefault(group => group.Count() > 1);
        if (duplicate is not null)
        {
            throw new InvalidOperationException(
                $"Physical VISA resource {duplicate.Key} is assigned to channels " +
                $"{string.Join(", ", duplicate.Select(item => item.Channel))}.");
        }
    }
}
