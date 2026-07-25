using Microsoft.Extensions.Logging.Abstractions;
using PrecisionLab.Acquisition;
using PrecisionLab.Domain;
using PrecisionLab.Storage;

namespace PrecisionLab.Core.Tests;

public sealed class PipelineTests
{
    [Fact]
    public async Task DisplayPublicationHappensOnlyAfterSqliteCommit()
    {
        await using var temporary = new TemporaryDirectory();
        await using var store = new SqliteSessionStore(
            Path.Combine(temporary.Path, "sessions.db"));
        await store.InitializeAsync(CancellationToken.None);
        var settings = new AcquisitionSettings { Resource = "SIM::PIPELINE" };
        Guid sessionId = await store.BeginSessionAsync(
            ChannelId.A,
            settings,
            new InstrumentIdentity(
                settings.InstrumentModel,
                "SIMULATOR",
                settings.Resource,
                "1",
                string.Empty,
                50),
            DateTimeOffset.UtcNow,
            CancellationToken.None);
        var hub = new MeasurementHub();
        var pipeline = new MeasurementPipeline(
            store,
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
        await pipeline.PublishAsync(
            sessionId,
            measurement,
            CancellationToken.None);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        Measurement displayed = await subscription.Reader.ReadAsync(timeout.Token);
        IReadOnlyList<Measurement> committed = await store.ReadMeasurementsAsync(
            sessionId,
            0,
            10,
            timeout.Token);

        Assert.Equal(measurement, displayed);
        Assert.Equal([measurement], committed);
        await pipeline.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task NonContiguousSequenceFailsInsteadOfSilentlyDroppingData()
    {
        await using var temporary = new TemporaryDirectory();
        await using var store = new SqliteSessionStore(
            Path.Combine(temporary.Path, "sessions.db"));
        await store.InitializeAsync(CancellationToken.None);
        var settings = new AcquisitionSettings { Resource = "SIM::ORDER" };
        Guid sessionId = await store.BeginSessionAsync(
            ChannelId.A,
            settings,
            new InstrumentIdentity(
                settings.InstrumentModel,
                "SIMULATOR",
                settings.Resource,
                "1",
                string.Empty,
                50),
            DateTimeOffset.UtcNow,
            CancellationToken.None);

        await Assert.ThrowsAsync<InvalidDataException>(
            () => store.AppendAsync(
                    sessionId,
                    new Measurement(
                        ChannelId.A,
                        1,
                        DateTimeOffset.UtcNow,
                        TimeSpan.Zero,
                        1,
                        MeasurementUnit.Volt,
                        null),
                    CancellationToken.None)
                .AsTask());
    }
}
