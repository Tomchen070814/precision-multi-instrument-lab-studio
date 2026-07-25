namespace PrecisionLab.Domain;

public enum ChannelId : byte
{
    A,
    B,
    C,
}

public sealed record Measurement(
    ChannelId Channel,
    long Sequence,
    DateTimeOffset TimestampUtc,
    TimeSpan Elapsed,
    double Value,
    MeasurementUnit Unit,
    double? InternalTemperatureC);

public sealed record InstrumentIdentity(
    InstrumentModel InstrumentModel,
    string ReportedModel,
    string Resource,
    string Firmware,
    string Options,
    double LineFrequencyHz);
