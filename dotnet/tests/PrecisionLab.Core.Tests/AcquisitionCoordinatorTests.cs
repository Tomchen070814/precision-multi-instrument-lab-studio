using Microsoft.Extensions.Logging.Abstractions;
using PrecisionLab.Acquisition;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Builtin;

namespace PrecisionLab.Core.Tests;

public sealed class AcquisitionCoordinatorTests
{
    [Fact]
    public async Task Three_simulated_channels_arm_and_publish_independently()
    {
        var sink = new RecordingSink();
        var hub = new MeasurementHub();
        using MeasurementSubscription subscription = hub.Subscribe();
        var pipeline = new MeasurementPipeline(
            sink,
            hub,
            NullLogger<MeasurementPipeline>.Instance);
        var coordinator = new AcquisitionCoordinator(
            new BuiltinInstrumentDriverFactory(),
            pipeline,
            NullLogger<AcquisitionCoordinator>.Instance);
        await pipeline.StartAsync(CancellationToken.None);

        await coordinator.StartChannelsAsync(
            Enum.GetValues<ChannelId>(),
            settings: null,
            CancellationToken.None);

        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var seen = new HashSet<ChannelId>();
        while (seen.Count < 3)
        {
            seen.Add((await subscription.Reader.ReadAsync(timeout.Token)).Channel);
        }

        ServiceSnapshot snapshot = coordinator.Snapshot();
        Assert.All(snapshot.Channels, channel => Assert.True(channel.SampleCount > 0));
        Assert.Equal(Enum.GetValues<ChannelId>(), seen.Order().ToArray());

        await coordinator.StopAsync(CancellationToken.None);
        await pipeline.StopAsync(CancellationToken.None);
        await sink.DisposeAsync();
    }

    private sealed class RecordingSink : IMeasurementSink
    {
        public ValueTask WriteAsync(
            Measurement measurement,
            CancellationToken cancellationToken) =>
            ValueTask.CompletedTask;

        public ValueTask FlushAsync(CancellationToken cancellationToken) =>
            ValueTask.CompletedTask;

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
