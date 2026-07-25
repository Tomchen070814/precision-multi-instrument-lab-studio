namespace PrecisionLab.Domain;

public enum StorageDurability : byte
{
    Maximum,
    Balanced,
    Throughput,
}

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

    public TimeSpan BurstAperture { get; init; } = TimeSpan.FromMicroseconds(1);

    public long? MaxSamples { get; init; }

    public bool IncludeTemperature { get; init; } = true;

    public StorageDurability Durability { get; init; } = StorageDurability.Maximum;

    public string VisaBackend { get; init; } = string.Empty;

    public AcquisitionSettings Validate()
    {
        if (string.IsNullOrWhiteSpace(Resource))
        {
            throw new ArgumentException("A resource address is required.", nameof(Resource));
        }

        InstrumentDescriptor descriptor = InstrumentCatalog.Get(InstrumentModel);
        if (!descriptor.Supports(Function))
        {
            throw new ArgumentException(
                $"{descriptor.ShortName} does not support {Function}.",
                nameof(Function));
        }

        if (!double.IsFinite(Nplc) ||
            Nplc < descriptor.MinimumNplc ||
            Nplc > descriptor.MaximumNplc)
        {
            throw new ArgumentOutOfRangeException(
                nameof(Nplc),
                $"NPLC must be between {descriptor.MinimumNplc} and {descriptor.MaximumNplc}.");
        }

        int minimumDigits = InstrumentModel == InstrumentModel.Fluke8508A ? 5 : 4;
        int maximumDigits = InstrumentModel == InstrumentModel.Fluke8508A ? 8 : 9;
        if (Digits < minimumDigits || Digits > maximumDigits)
        {
            throw new ArgumentOutOfRangeException(
                nameof(Digits),
                $"Digits must be between {minimumDigits} and {maximumDigits}.");
        }

        bool burst = Function is
            MeasurementFunction.DigitizeDc or MeasurementFunction.DigitizeAc;
        TimeSpan minimumInterval = burst
            ? TimeSpan.FromMicroseconds(10)
            : TimeSpan.FromMilliseconds(1);
        if (SampleInterval < minimumInterval)
        {
            throw new ArgumentOutOfRangeException(
                nameof(SampleInterval),
                burst
                    ? "3458A burst acquisition requires at least a 10 µs interval."
                    : "Continuous acquisition requires at least a 1 ms interval.");
        }

        if (MaxSamples is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(MaxSamples), "MaxSamples must be positive.");
        }

        if (burst)
        {
            if (InstrumentModel != InstrumentModel.Keysight3458A)
            {
                throw new ArgumentException(
                    "Digitize modes are available only for the 3458A.",
                    nameof(InstrumentModel));
            }

            if (MaxSamples is null or > 148_000)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(MaxSamples),
                    "3458A burst mode requires 1 to 148000 samples.");
            }

            if (BurstAperture < TimeSpan.FromTicks(5) ||
                BurstAperture > TimeSpan.FromSeconds(1) ||
                BurstAperture > SampleInterval)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(BurstAperture),
                    "Burst aperture must be 500 ns to 1 s and not exceed the interval.");
            }
        }

        string autozero = Autozero.ToUpperInvariant();
        if (autozero is not ("ON" or "OFF" or "ONCE"))
        {
            throw new ArgumentException(
                "Autozero must be ON, OFF, or ONCE.",
                nameof(Autozero));
        }

        if (!Resource.StartsWith("SIM::", StringComparison.OrdinalIgnoreCase) &&
            descriptor.RequiresGpib &&
            !(Resource.StartsWith("GPIB", StringComparison.OrdinalIgnoreCase) &&
              Resource.EndsWith("::INSTR", StringComparison.OrdinalIgnoreCase)))
        {
            throw new ArgumentException(
                $"{descriptor.ShortName} requires a GPIB VISA INSTR resource.",
                nameof(Resource));
        }

        return this;
    }
}
