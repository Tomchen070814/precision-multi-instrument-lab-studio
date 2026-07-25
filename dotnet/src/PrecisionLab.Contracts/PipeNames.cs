using System.Text.RegularExpressions;

namespace PrecisionLab.Contracts;

public static partial class PipeNames
{
    private static readonly string InstanceSuffix = ResolveInstanceSuffix();

    public static string Control => $"precisionlab.control.v1{InstanceSuffix}";

    public static string Data => $"precisionlab.data.v1{InstanceSuffix}";

    public const int ProtocolVersion = 1;

    private static string ResolveInstanceSuffix()
    {
        string? instance = Environment.GetEnvironmentVariable("PRECISIONLAB_INSTANCE");
        if (string.IsNullOrWhiteSpace(instance))
        {
            return string.Empty;
        }

        string safe = UnsafePipeCharacters().Replace(instance.Trim(), "-");
        return $".{safe[..Math.Min(48, safe.Length)]}";
    }

    [GeneratedRegex(@"[^A-Za-z0-9_.-]+")]
    private static partial Regex UnsafePipeCharacters();
}
