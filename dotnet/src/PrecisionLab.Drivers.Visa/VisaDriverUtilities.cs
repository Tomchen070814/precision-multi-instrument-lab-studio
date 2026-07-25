using System.Collections.Concurrent;
using System.Globalization;
using System.Text.RegularExpressions;
using PrecisionLab.Domain;

namespace PrecisionLab.Drivers.Visa;

public sealed class InstrumentDriverException : IOException
{
    public InstrumentDriverException(string message)
        : base(message)
    {
    }

    public InstrumentDriverException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

internal static partial class VisaDriverUtilities
{
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> BusLocks =
        new(StringComparer.OrdinalIgnoreCase);

    public static SemaphoreSlim BusLock(string resource)
    {
        string normalized = resource.Trim().ToUpperInvariant();
        string key = normalized.StartsWith("GPIB", StringComparison.Ordinal)
            ? normalized.Split("::", 2, StringSplitOptions.None)[0]
            : normalized;
        return BusLocks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));
    }

    public static bool IsGpibInstrument(string resource) =>
        resource.Trim().StartsWith("GPIB", StringComparison.OrdinalIgnoreCase) &&
        resource.Trim().EndsWith("::INSTR", StringComparison.OrdinalIgnoreCase);

    public static bool IsVisaInstrument(string resource) =>
        resource.Trim().EndsWith("::INSTR", StringComparison.OrdinalIgnoreCase) ||
        resource.Trim().EndsWith("::SOCKET", StringComparison.OrdinalIgnoreCase);

    public static double[] ParseNumbers(string payload) =>
        NumberPattern()
            .Matches(payload)
            .Select(match => double.Parse(
                match.Value,
                NumberStyles.Float,
                CultureInfo.InvariantCulture))
            .ToArray();

    public static string LegacyFunctionCommand(MeasurementFunction function) =>
        function switch
        {
            MeasurementFunction.DcVoltage => "DCV",
            MeasurementFunction.AcVoltage => "ACV",
            MeasurementFunction.Resistance2Wire => "OHM",
            MeasurementFunction.Resistance4Wire => "OHMF",
            MeasurementFunction.DcCurrent => "DCI",
            MeasurementFunction.AcCurrent => "ACI",
            MeasurementFunction.AcDcVoltage => "ACDCV",
            MeasurementFunction.AcDcCurrent => "ACDCI",
            MeasurementFunction.Frequency => "FREQ",
            MeasurementFunction.Period => "PER",
            MeasurementFunction.DigitizeDc => "DSDC",
            MeasurementFunction.DigitizeAc => "DSAC",
            _ => throw new ArgumentOutOfRangeException(nameof(function)),
        };

    [GeneratedRegex(@"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")]
    private static partial Regex NumberPattern();
}
