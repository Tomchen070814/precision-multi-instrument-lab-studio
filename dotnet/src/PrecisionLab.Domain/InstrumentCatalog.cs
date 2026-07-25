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
    bool SupportsBurst);

public static class InstrumentCatalog
{
    public static IReadOnlyList<InstrumentDescriptor> All { get; } =
    [
        new(InstrumentModel.Keysight3458A, "Keysight", "3458A", InstrumentProtocol.HpIb3458A, true, true),
        new(InstrumentModel.Keysight34465A, "Keysight", "34465A", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.Keysight34470A, "Keysight", "34470A", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.Fluke8588A, "Fluke", "8588A", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.Fluke8508A, "Fluke", "8508A", InstrumentProtocol.Ieee488Fluke8508A, true, false),
        new(InstrumentModel.Fluke8846A, "Fluke", "8846A", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.KeithleyDmm7510, "Keithley", "DMM7510", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.RohdeSchwarzHmc8012, "Rohde & Schwarz", "HMC8012", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.RigolDm3068, "Rigol", "DM3068", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.SiglentSdm3065X, "Siglent", "SDM3065X", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.GwInstekGdm9061, "GW Instek", "GDM-9061", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.HiokiDm7276, "Hioki", "DM7276", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.YokogawaDm7560, "Yokogawa", "DM7560", InstrumentProtocol.Scpi, false, false),
        new(InstrumentModel.PicotestM3510A, "Picotest", "M3510A", InstrumentProtocol.Scpi, false, false),
    ];

    public static InstrumentDescriptor Get(InstrumentModel model) =>
        All.First(item => item.Model == model);
}
