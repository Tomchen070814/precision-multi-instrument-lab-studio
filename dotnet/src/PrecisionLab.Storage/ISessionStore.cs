using PrecisionLab.Domain;

namespace PrecisionLab.Storage;

public enum SessionCompletionStatus : byte
{
    Running,
    Completed,
    Stopped,
    Faulted,
    Interrupted,
}

public sealed record SessionInfo(
    Guid Id,
    ChannelId Channel,
    InstrumentModel InstrumentModel,
    MeasurementFunction Function,
    string Resource,
    DateTimeOffset StartedUtc,
    DateTimeOffset? EndedUtc,
    SessionCompletionStatus Status,
    MeasurementUnit Unit,
    long SampleCount,
    long CommittedSequence,
    string? Error);

public interface ISessionStore : IAsyncDisposable
{
    string DatabasePath { get; }

    ValueTask InitializeAsync(CancellationToken cancellationToken);

    ValueTask<Guid> BeginSessionAsync(
        ChannelId channel,
        AcquisitionSettings settings,
        InstrumentIdentity identity,
        DateTimeOffset startedUtc,
        CancellationToken cancellationToken);

    ValueTask AppendAsync(
        Guid sessionId,
        Measurement measurement,
        CancellationToken cancellationToken);

    ValueTask AppendBatchAsync(
        Guid sessionId,
        IReadOnlyList<Measurement> measurements,
        CancellationToken cancellationToken);

    ValueTask CompleteSessionAsync(
        Guid sessionId,
        SessionCompletionStatus status,
        string? failureMessage,
        CancellationToken cancellationToken);

    ValueTask<IReadOnlyList<SessionInfo>> ListSessionsAsync(
        int limit,
        CancellationToken cancellationToken);

    ValueTask<IReadOnlyList<Measurement>> ReadMeasurementsAsync(
        Guid sessionId,
        long firstSequence,
        int limit,
        CancellationToken cancellationToken);
}
