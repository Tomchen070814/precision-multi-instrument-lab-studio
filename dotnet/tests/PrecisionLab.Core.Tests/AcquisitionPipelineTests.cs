using Microsoft.Extensions.Logging.Abstractions;
using PrecisionLab.Acquisition;
using PrecisionLab.Domain;

namespace PrecisionLab.Core.Tests;

public sealed class AcquisitionPipelineTests
{
    [Fact]
    public async Task Durable_sink_runs_before_display_broadcast()
    {
        var sink = new RecordingSink();
        var hub = new MeasurementHub();
        using MeasurementSubscription subscription = hub.Subscribe();
        var pipeline = new MeasurementPipeline(
            sink,
            hub,
            NullLogger<MeasurementPipeline>.Instance,
            capacity: 4);
        await pipeline.StartAsync(CancellationToken.None);
        var measurement = new Measurement(
            ChannelId.A,
            1,
            DateTimeOffset.UtcNow,
            TimeSpan.FromSeconds(1),
            10,
            MeasurementUnit.Volt,
            null);

        await pipeline.PublishAsync(measurement, CancellationToken.None);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        Measurement displayed = await subscription.Reader.ReadAsync(timeout.Token);

        Assert.Equal(measurement, displayed);
        Assert.Equal([measurement], sink.Measurements);
        await pipeline.StopAsync(CancellationToken.None);
        await sink.DisposeAsync();
    }

    private sealed class RecordingSink : IMeasurementSink
    {
        public List<Measurement> Measurements { get; } = [];

        public ValueTask WriteAsync(
            Measurement measurement,
            CancellationToken cancellationToken)
        {
            Measurements.Add(measurement);
            return ValueTask.CompletedTask;
        }

        public ValueTask FlushAsync(CancellationToken cancellationToken) =>
            ValueTask.CompletedTask;

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
