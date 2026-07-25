using Microsoft.Extensions.Logging.Abstractions;
using PrecisionLab.Acquisition;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Builtin;
using PrecisionLab.Storage;

namespace PrecisionLab.Core.Tests;

public sealed class AcquisitionCoordinatorTests
{
    [Fact]
    public async Task ThreeSimulatedChannelsArmPersistAndPublishIndependently()
    {
        await using var temporary = new TemporaryDirectory();
        await using var store = new SqliteSessionStore(
            Path.Combine(temporary.Path, "sessions.db"));
        var hub = new MeasurementHub();
        using MeasurementSubscription subscription = hub.Subscribe();
        var pipeline = new MeasurementPipeline(
            store,
            hub,
            NullLogger<MeasurementPipeline>.Instance);
        var coordinator = new AcquisitionCoordinator(
            new BuiltinInstrumentDriverFactory(),
            pipeline,
            store,
            NullLogger<AcquisitionCoordinator>.Instance);
        await pipeline.StartAsync(CancellationToken.None);

        var settings = Enum.GetValues<ChannelId>().ToDictionary(
            channel => channel,
            channel => new AcquisitionSettings
            {
                Resource = $"SIM::{channel}",
                SampleInterval = TimeSpan.FromMilliseconds(5),
                MaxSamples = 10,
            });
        await coordinator.StartChannelsAsync(
            Enum.GetValues<ChannelId>(),
            settings,
            CancellationToken.None);

        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var seen = new HashSet<ChannelId>();
        while (seen.Count < 3)
        {
            seen.Add((await subscription.Reader.ReadAsync(timeout.Token)).Channel);
        }

        await WaitForStoppedAsync(coordinator, timeout.Token);
        ServiceSnapshot snapshot = coordinator.Snapshot();
        Assert.All(snapshot.Channels, channel => Assert.Equal(10, channel.CommittedSamples));
        Assert.Equal(Enum.GetValues<ChannelId>(), seen.Order().ToArray());
        Assert.Equal(
            3,
            (await store.ListSessionsAsync(10, timeout.Token)).Count);

        await coordinator.StopAsync(CancellationToken.None);
        await pipeline.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task SamePhysicalVisaResourceCannotBeAssignedTwice()
    {
        await using var temporary = new TemporaryDirectory();
        await using var store = new SqliteSessionStore(
            Path.Combine(temporary.Path, "sessions.db"));
        var coordinator = new AcquisitionCoordinator(
            new BuiltinInstrumentDriverFactory(),
            new NullPublisher(),
            store,
            NullLogger<AcquisitionCoordinator>.Instance);
        var settings = new Dictionary<ChannelId, AcquisitionSettings>
        {
            [ChannelId.A] = new()
            {
                InstrumentModel = InstrumentModel.Keysight34470A,
                Resource = "TCPIP0::192.0.2.1::inst0::INSTR",
            },
            [ChannelId.B] = new()
            {
                InstrumentModel = InstrumentModel.Keysight34470A,
                Resource = "tcpip0::192.0.2.1::inst0::instr",
            },
        };

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => coordinator.StartChannelsAsync(
                [ChannelId.A, ChannelId.B],
                settings,
                CancellationToken.None));
    }

    private static async Task WaitForStoppedAsync(
        AcquisitionCoordinator coordinator,
        CancellationToken cancellationToken)
    {
        while (coordinator.Snapshot().Channels.Any(
                   item => item.State is not ChannelState.Stopped))
        {
            await Task.Delay(20, cancellationToken);
        }
    }

    private sealed class NullPublisher : IMeasurementPublisher
    {
        public ValueTask PublishAsync(
            Guid sessionId,
            Measurement measurement,
            CancellationToken cancellationToken) =>
            ValueTask.CompletedTask;
    }
}
