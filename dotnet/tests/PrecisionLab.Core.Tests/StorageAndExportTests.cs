using System.IO.Compression;
using PrecisionLab.Domain;
using PrecisionLab.Export;
using PrecisionLab.Storage;

namespace PrecisionLab.Core.Tests;

public sealed class StorageAndExportTests
{
    [Fact]
    public async Task ReopeningDatabaseMarksUnfinishedSessionInterrupted()
    {
        await using var temporary = new TemporaryDirectory();
        string database = Path.Combine(temporary.Path, "sessions.db");
        Guid sessionId;
        await using (var first = new SqliteSessionStore(database))
        {
            await first.InitializeAsync(CancellationToken.None);
            sessionId = await first.BeginSessionAsync(
                ChannelId.B,
                Settings("SIM::RECOVERY"),
                Identity("SIM::RECOVERY"),
                DateTimeOffset.UtcNow,
                CancellationToken.None);
            await first.AppendAsync(
                sessionId,
                Reading(ChannelId.B, 0, 1.25),
                CancellationToken.None);
        }

        await using var reopened = new SqliteSessionStore(database);
        await reopened.InitializeAsync(CancellationToken.None);
        SessionInfo recovered = Assert.Single(
            await reopened.ListSessionsAsync(10, CancellationToken.None));

        Assert.Equal(sessionId, recovered.Id);
        Assert.Equal(SessionCompletionStatus.Interrupted, recovered.Status);
        Assert.Equal(1, recovered.SampleCount);
        Assert.Equal(0, recovered.CommittedSequence);
    }

    [Fact]
    public async Task CsvExportAndImportRoundTripMeasurements()
    {
        await using var temporary = new TemporaryDirectory();
        await using var store = new SqliteSessionStore(
            Path.Combine(temporary.Path, "sessions.db"));
        await store.InitializeAsync(CancellationToken.None);
        Guid sessionId = await store.BeginSessionAsync(
            ChannelId.A,
            Settings("SIM::CSV"),
            Identity("SIM::CSV"),
            DateTimeOffset.UtcNow,
            CancellationToken.None);
        for (int index = 0; index < 4; index++)
        {
            await store.AppendAsync(
                sessionId,
                Reading(ChannelId.A, index, 10 + index),
                CancellationToken.None);
        }

        await store.CompleteSessionAsync(
            sessionId,
            SessionCompletionStatus.Completed,
            null,
            CancellationToken.None);
        string csv = Path.Combine(temporary.Path, "export.csv");
        await CsvDataExchange.ExportSessionAsync(
            csv,
            sessionId,
            store,
            CancellationToken.None);
        ImportedMeasurementData imported = await CsvDataExchange.ImportAsync(
            csv,
            CancellationToken.None);

        Assert.Equal([10, 11, 12, 13], imported.Values);
        Assert.Equal([0, 1, 2, 3], imported.ElapsedSeconds);
        Assert.Equal("V", imported.Unit);
    }

    [Fact]
    public async Task DiagnosticZipExcludesRawSamples()
    {
        await using var temporary = new TemporaryDirectory();
        string path = await DiagnosticReportWriter.CreateAsync(
            Path.Combine(temporary.Path, "diagnostic.zip"),
            new ServiceSnapshot(
                1,
                "test",
                DateTimeOffset.UtcNow,
                Environment.ProcessId,
                Environment.WorkingSet,
                []),
            Path.Combine(temporary.Path, "sessions.db"),
            "en",
            cancellationToken: CancellationToken.None);

        using ZipArchive archive = ZipFile.OpenRead(path);
        string[] names = archive.Entries.Select(item => item.FullName).ToArray();
        Assert.Contains("diagnostic.json", names);
        Assert.Contains("diagnostic.html", names);
        Assert.DoesNotContain(
            names,
            name => name.Contains("sample", StringComparison.OrdinalIgnoreCase));
    }

    private static AcquisitionSettings Settings(string resource) =>
        new() { Resource = resource };

    private static InstrumentIdentity Identity(string resource) =>
        new(
            InstrumentModel.Keysight3458A,
            "SIMULATOR",
            resource,
            "1",
            string.Empty,
            50);

    private static Measurement Reading(
        ChannelId channel,
        long sequence,
        double value) =>
        new(
            channel,
            sequence,
            DateTimeOffset.UnixEpoch + TimeSpan.FromSeconds(sequence),
            TimeSpan.FromSeconds(sequence),
            value,
            MeasurementUnit.Volt,
            null);
}
