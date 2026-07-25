namespace PrecisionLab.Domain;

public enum ChannelState : byte
{
    Stopped,
    Connecting,
    Armed,
    Running,
    Stopping,
    Faulted,
}

public sealed record ChannelSnapshot(
    ChannelId Channel,
    ChannelState State,
    InstrumentModel InstrumentModel,
    MeasurementFunction Function,
    string Resource,
    string ReportedModel,
    long SampleCount,
    double? LastValue,
    MeasurementUnit Unit,
    DateTimeOffset? StartedUtc,
    string? Error,
    Guid? SessionId = null,
    long CommittedSamples = 0);

public sealed record ServiceSnapshot(
    int ProtocolVersion,
    string ServiceVersion,
    DateTimeOffset ServiceStartedUtc,
    int ServiceProcessId,
    long ServiceWorkingSetBytes,
    IReadOnlyList<ChannelSnapshot> Channels);
