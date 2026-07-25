namespace PrecisionLab.Domain;

public enum ChannelId : byte
{
    A = 0,
    B = 1,
    C = 2,
}

public enum ChannelState
{
    Stopped = 0,
    Connecting = 1,
    Armed = 2,
    Running = 3,
    Stopping = 4,
    Faulted = 5,
}

public enum InstrumentModel : byte
{
    Keysight3458A = 0,
    Keysight34465A = 1,
    Keysight34470A = 2,
    Fluke8588A = 3,
    Fluke8508A = 4,
    Fluke8846A = 5,
    KeithleyDmm7510 = 6,
    RohdeSchwarzHmc8012 = 7,
    RigolDm3068 = 8,
    SiglentSdm3065X = 9,
    GwInstekGdm9061 = 10,
    HiokiDm7276 = 11,
    YokogawaDm7560 = 12,
    PicotestM3510A = 13,
}

public enum InstrumentProtocol
{
    HpIb3458A = 0,
    Ieee4888508A = 1,
    SpecializedScpi8588A = 2,
    ScpiProfile = 3,
    DigitalTwin = 4,
}

public enum MeasurementFunction
{
    DcVoltage = 0,
    AcVoltage = 1,
    AcDcVoltage = 2,
    Resistance2Wire = 3,
    Resistance4Wire = 4,
    DcCurrent = 5,
    AcCurrent = 6,
    AcDcCurrent = 7,
    Frequency = 8,
    Period = 9,
    DigitizeDc = 10,
    DigitizeAc = 11,
}

public enum MeasurementUnit : byte
{
    Volt = 0,
    Ohm = 1,
    Ampere = 2,
    Hertz = 3,
    Second = 4,
}

public static class MeasurementMetadata
{
    public static MeasurementUnit Unit(this MeasurementFunction function) =>
        function switch
        {
            MeasurementFunction.DcVoltage or
            MeasurementFunction.AcVoltage or
            MeasurementFunction.AcDcVoltage or
            MeasurementFunction.DigitizeDc or
            MeasurementFunction.DigitizeAc => MeasurementUnit.Volt,
            MeasurementFunction.Resistance2Wire or
            MeasurementFunction.Resistance4Wire => MeasurementUnit.Ohm,
            MeasurementFunction.DcCurrent or
            MeasurementFunction.AcCurrent or
            MeasurementFunction.AcDcCurrent => MeasurementUnit.Ampere,
            MeasurementFunction.Frequency => MeasurementUnit.Hertz,
            MeasurementFunction.Period => MeasurementUnit.Second,
            _ => throw new ArgumentOutOfRangeException(nameof(function)),
        };

    public static string Symbol(this MeasurementUnit unit) =>
        unit switch
        {
            MeasurementUnit.Volt => "V",
            MeasurementUnit.Ohm => "Ω",
            MeasurementUnit.Ampere => "A",
            MeasurementUnit.Hertz => "Hz",
            MeasurementUnit.Second => "s",
            _ => throw new ArgumentOutOfRangeException(nameof(unit)),
        };
}

public sealed record InstrumentIdentity(
    InstrumentModel Model,
    string Manufacturer,
    string ReportedModel,
    string Resource,
    InstrumentProtocol Protocol,
    string Firmware = "SIM-1.0");

public sealed record Measurement(
    ChannelId Channel,
    long Sequence,
    DateTimeOffset TimestampUtc,
    TimeSpan Elapsed,
    double Value,
    MeasurementUnit Unit,
    double? InternalTemperatureC);

public sealed record AcquisitionSettings
{
    public InstrumentModel InstrumentModel { get; init; } = InstrumentModel.Keysight3458A;

    public string Resource { get; init; } = "SIM::3458A";

    public MeasurementFunction Function { get; init; } = MeasurementFunction.DcVoltage;

    public TimeSpan SampleInterval { get; init; } = TimeSpan.FromSeconds(1);

    public double Nplc { get; init; } = 10;

    public int Digits { get; init; } = 8;

    public string Autozero { get; init; } = "ON";

    public long? MaxSamples { get; init; }

    public AcquisitionSettings Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(Resource);
        if (SampleInterval <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(SampleInterval),
                "Sample interval must be positive.");
        }

        if (Nplc <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(Nplc));
        }

        if (Digits is < 3 or > 10)
        {
            throw new ArgumentOutOfRangeException(nameof(Digits));
        }

        if (MaxSamples is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(MaxSamples));
        }

        return this;
    }
}

public sealed record ChannelSnapshot(
    ChannelId Channel,
    ChannelState State,
    InstrumentModel Model,
    MeasurementFunction Function,
    string Resource,
    string ReportedModel,
    long SampleCount,
    double? LastValue,
    MeasurementUnit Unit,
    DateTimeOffset? StartedUtc,
    string? Error);

public sealed record ServiceSnapshot(
    int ProtocolVersion,
    string ServiceVersion,
    DateTimeOffset ServiceStartedUtc,
    int ProcessId,
    long WorkingSetBytes,
    IReadOnlyList<ChannelSnapshot> Channels);
