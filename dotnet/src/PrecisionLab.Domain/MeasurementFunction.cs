namespace PrecisionLab.Domain;

public enum MeasurementFunction : byte
{
    DcVoltage,
    AcVoltage,
    Resistance2Wire,
    Resistance4Wire,
    DcCurrent,
    AcCurrent,
    AcDcVoltage,
    AcDcCurrent,
    Frequency,
    Period,
    DigitizeDc,
    DigitizeAc,
}

public enum MeasurementUnit : byte
{
    Volt,
    Ohm,
    Ampere,
    Hertz,
    Second,
}

public static class MeasurementFunctionExtensions
{
    public static MeasurementUnit Unit(this MeasurementFunction function) =>
        function switch
        {
            MeasurementFunction.DcVoltage
                or MeasurementFunction.AcVoltage
                or MeasurementFunction.AcDcVoltage
                or MeasurementFunction.DigitizeDc
                or MeasurementFunction.DigitizeAc => MeasurementUnit.Volt,
            MeasurementFunction.Resistance2Wire
                or MeasurementFunction.Resistance4Wire => MeasurementUnit.Ohm,
            MeasurementFunction.DcCurrent
                or MeasurementFunction.AcCurrent
                or MeasurementFunction.AcDcCurrent => MeasurementUnit.Ampere,
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
