using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Builtin;

public static class InstrumentCatalog
{
    private static readonly IReadOnlySet<MeasurementFunction> StandardFunctions =
        new HashSet<MeasurementFunction>
        {
            MeasurementFunction.DcVoltage,
            MeasurementFunction.AcVoltage,
            MeasurementFunction.Resistance2Wire,
            MeasurementFunction.Resistance4Wire,
            MeasurementFunction.DcCurrent,
            MeasurementFunction.AcCurrent,
            MeasurementFunction.Frequency,
            MeasurementFunction.Period,
        };

    private static readonly IReadOnlyDictionary<InstrumentModel, InstrumentDescriptor> Entries =
        new[]
        {
            Descriptor(
                InstrumentModel.Keysight3458A,
                "Keysight",
                "3458A",
                InstrumentProtocol.HpIb3458A,
                StandardFunctions.Concat(
                    [
                        MeasurementFunction.AcDcVoltage,
                        MeasurementFunction.AcDcCurrent,
                        MeasurementFunction.DigitizeDc,
                        MeasurementFunction.DigitizeAc,
                    ])),
            Descriptor(
                InstrumentModel.Keysight34465A,
                "Keysight",
                "34465A",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.Keysight34470A,
                "Keysight",
                "34470A",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.Fluke8588A,
                "Fluke",
                "8588A",
                InstrumentProtocol.SpecializedScpi8588A,
                StandardFunctions,
                supportsTemperature: true),
            Descriptor(
                InstrumentModel.Fluke8508A,
                "Fluke",
                "8508A",
                InstrumentProtocol.Ieee4888508A,
                StandardFunctions.Where(
                    function => function is not (
                        MeasurementFunction.Frequency or MeasurementFunction.Period))),
            Descriptor(
                InstrumentModel.Fluke8846A,
                "Fluke",
                "8846A",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.KeithleyDmm7510,
                "Keithley",
                "DMM7510",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.RohdeSchwarzHmc8012,
                "Rohde & Schwarz",
                "HMC8012",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.RigolDm3068,
                "Rigol",
                "DM3068",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.SiglentSdm3065X,
                "Siglent",
                "SDM3065X",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.GwInstekGdm9061,
                "GW Instek",
                "GDM-9061",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.HiokiDm7276,
                "Hioki",
                "DM7276",
                InstrumentProtocol.ScpiProfile,
                [MeasurementFunction.DcVoltage],
                supportsTemperature: true),
            Descriptor(
                InstrumentModel.YokogawaDm7560,
                "Yokogawa",
                "DM7560",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
            Descriptor(
                InstrumentModel.PicotestM3510A,
                "Picotest",
                "M3510A",
                InstrumentProtocol.ScpiProfile,
                StandardFunctions),
        }.ToDictionary(item => item.Model);

    public static IReadOnlyCollection<InstrumentDescriptor> All => Entries.Values.ToArray();

    public static InstrumentDescriptor Get(InstrumentModel model) =>
        Entries.TryGetValue(model, out InstrumentDescriptor? descriptor)
            ? descriptor
            : throw new NotSupportedException($"Instrument model '{model}' is not cataloged.");

    private static InstrumentDescriptor Descriptor(
        InstrumentModel model,
        string manufacturer,
        string modelName,
        InstrumentProtocol protocol,
        IEnumerable<MeasurementFunction> functions,
        bool supportsTemperature = false) =>
        new(
            model,
            manufacturer,
            modelName,
            protocol,
            functions.ToHashSet(),
            supportsTemperature);
}
