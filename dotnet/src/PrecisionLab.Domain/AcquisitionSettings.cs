namespace PrecisionLab.Domain;

public sealed record AcquisitionSettings
{
    public InstrumentModel InstrumentModel { get; init; } = InstrumentModel.Keysight3458A;

    public MeasurementFunction Function { get; init; } = MeasurementFunction.DcVoltage;

    public string Resource { get; init; } = "SIM::3458A";

    public string MeasurementRange { get; init; } = "AUTO";

    public double Nplc { get; init; } = 10;

    public int Digits { get; init; } = 8;

    public string Autozero { get; init; } = "ON";

    public TimeSpan SampleInterval { get; init; } = TimeSpan.FromSeconds(1);

    public long? MaxSamples { get; init; }

    public AcquisitionSettings Validate()
    {
        if (string.IsNullOrWhiteSpace(Resource))
        {
            throw new ArgumentException("A resource address is required.", nameof(Resource));
        }

        if (!double.IsFinite(Nplc) || Nplc < 0 || Nplc > 1_024)
        {
            throw new ArgumentOutOfRangeException(nameof(Nplc), "NPLC must be between 0 and 1024.");
        }

        if (Digits is < 4 or > 9)
        {
            throw new ArgumentOutOfRangeException(nameof(Digits), "Digits must be between 4 and 9.");
        }

        if (SampleInterval < TimeSpan.FromMilliseconds(1))
        {
            throw new ArgumentOutOfRangeException(
                nameof(SampleInterval),
                "The phase-one precision pipeline requires at least a 1 ms interval.");
        }

        if (MaxSamples is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(MaxSamples), "MaxSamples must be positive.");
        }

        return this;
    }
}
