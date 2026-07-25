namespace PrecisionLab.Domain;

public sealed record SessionSummary(
    Guid Id,
    ChannelId Channel,
    InstrumentModel InstrumentModel,
    MeasurementFunction Function,
    string Resource,
    DateTimeOffset StartedUtc,
    DateTimeOffset? EndedUtc,
    string Status,
    MeasurementUnit Unit,
    long SampleCount,
    long CommittedSequence,
    string? Error);
