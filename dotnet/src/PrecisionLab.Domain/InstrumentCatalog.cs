namespace PrecisionLab.Domain;

public enum InstrumentModel : byte
{
    Keysight3458A,
    Keysight34465A,
    Keysight34470A,
    Fluke8588A,
    Fluke8508A,
    Fluke8846A,
    KeithleyDmm7510,
    RohdeSchwarzHmc8012,
    RigolDm3068,
    SiglentSdm3065X,
    GwInstekGdm9061,
    HiokiDm7276,
    YokogawaDm7560,
    PicotestM3510A,
}

public enum InstrumentProtocol : byte
{
    HpIb3458A,
    Ieee488Fluke8508A,
    Scpi,
}

public sealed record InstrumentDescriptor(
    InstrumentModel Model,
    string Manufacturer,
    string ShortName,
    InstrumentProtocol Protocol,
    bool RequiresGpib,
    bool SupportsBurst,
    bool SupportsAutozero,
    double MinimumNplc,
    double MaximumNplc,
    IReadOnlyList<MeasurementFunction> SupportedFunctions,
    IReadOnlyList<string> IdentityTokens);

public static class InstrumentCatalog
{
    private static readonly MeasurementFunction[] StandardFunctions =
    [
        MeasurementFunction.DcVoltage,
        MeasurementFunction.AcVoltage,
        MeasurementFunction.Resistance2Wire,
        MeasurementFunction.Resistance4Wire,
        MeasurementFunction.DcCurrent,
        MeasurementFunction.AcCurrent,
        MeasurementFunction.Frequency,
        MeasurementFunction.Period,
    ];

    private static readonly MeasurementFunction[] Keysight3458AFunctions =
    [
        MeasurementFunction.DcVoltage,
        MeasurementFunction.AcVoltage,
        MeasurementFunction.AcDcVoltage,
        MeasurementFunction.Resistance2Wire,
        MeasurementFunction.Resistance4Wire,
        MeasurementFunction.DcCurrent,
        MeasurementFunction.AcCurrent,
        MeasurementFunction.AcDcCurrent,
        MeasurementFunction.Frequency,
        MeasurementFunction.Period,
        MeasurementFunction.DigitizeDc,
        MeasurementFunction.DigitizeAc,
    ];

    private static readonly MeasurementFunction[] Fluke8508AFunctions =
    [
        MeasurementFunction.DcVoltage,
        MeasurementFunction.AcVoltage,
        MeasurementFunction.Resistance2Wire,
        MeasurementFunction.Resistance4Wire,
        MeasurementFunction.DcCurrent,
        MeasurementFunction.AcCurrent,
    ];

    public static IReadOnlyList<InstrumentDescriptor> All { get; } =
    [
        new(InstrumentModel.Keysight3458A, "Keysight", "3458A", InstrumentProtocol.HpIb3458A, true, true, true, 0, 1_000, Keysight3458AFunctions, ["3458"]),
        new(InstrumentModel.Keysight34465A, "Keysight", "34465A", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["34465A"]),
        new(InstrumentModel.Keysight34470A, "Keysight", "34470A", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["34470A"]),
        new(InstrumentModel.Fluke8588A, "Fluke", "8588A", InstrumentProtocol.Scpi, false, false, false, 0, 600, StandardFunctions, ["8588A"]),
        new(InstrumentModel.Fluke8508A, "Fluke", "8508A", InstrumentProtocol.Ieee488Fluke8508A, true, false, false, 0, 1_024, Fluke8508AFunctions, ["FLUKE", "8508A"]),
        new(InstrumentModel.Fluke8846A, "Fluke", "8846A", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["8846A"]),
        new(InstrumentModel.KeithleyDmm7510, "Keithley", "DMM7510", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["DMM7510"]),
        new(InstrumentModel.RohdeSchwarzHmc8012, "Rohde & Schwarz", "HMC8012", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["HMC8012"]),
        new(InstrumentModel.RigolDm3068, "Rigol", "DM3068", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["DM3068"]),
        new(InstrumentModel.SiglentSdm3065X, "Siglent", "SDM3065X", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["SDM3065X"]),
        new(InstrumentModel.GwInstekGdm9061, "GW Instek", "GDM-9061", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["GDM-9061", "GDM9061"]),
        new(InstrumentModel.HiokiDm7276, "Hioki", "DM7276", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, [MeasurementFunction.DcVoltage], ["DM7276"]),
        new(InstrumentModel.YokogawaDm7560, "Yokogawa", "DM7560", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["DM7560"]),
        new(InstrumentModel.PicotestM3510A, "Picotest", "M3510A", InstrumentProtocol.Scpi, false, false, true, 0, 1_000, StandardFunctions, ["M3510A"]),
    ];

    public static InstrumentDescriptor Get(InstrumentModel model) =>
        All.First(item => item.Model == model);

    public static bool Supports(
        this InstrumentDescriptor descriptor,
        MeasurementFunction function) =>
        descriptor.SupportedFunctions.Contains(function);
}
