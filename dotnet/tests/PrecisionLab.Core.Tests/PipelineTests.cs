using Microsoft.Extensions.Logging.Abstractions;
using PrecisionLab.Acquisition;
using PrecisionLab.Domain;

namespace PrecisionLab.Core.Tests;

public sealed class PipelineTests
{
    [Fact]
    public async Task DisplayPublicationHappensOnlyAfterDurableFlush()
    {
        var sink = new TrackingSink();
        var hub = new MeasurementHub();
        var pipeline = new MeasurementPipeline(
            sink,
            hub,
            NullLogger<MeasurementPipeline>.Instance,
            capacity: 2);
        using MeasurementSubscription subscription = hub.Subscribe();
        await pipeline.StartAsync(CancellationToken.None);

        var measurement = new Measurement(
            ChannelId.A,
            0,
            DateTimeOffset.UtcNow,
            TimeSpan.Zero,
            0.1,
            MeasurementUnit.Volt,
            null);
        await pipeline.PublishAsync(measurement, CancellationToken.None);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        Measurement displayed = await subscription.Reader.ReadAsync(timeout.Token);

        Assert.Equal(measurement, displayed);
        Assert.True(sink.Flushed);

        await pipeline.StopAsync(CancellationToken.None);
    }

    private sealed class TrackingSink : IMeasurementSink
    {
        public bool Flushed { get; private set; }

        public ValueTask WriteAsync(
            Measurement measurement,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Flushed = false;
            return ValueTask.CompletedTask;
        }

        public ValueTask FlushAsync(CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Flushed = true;
            return ValueTask.CompletedTask;
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
