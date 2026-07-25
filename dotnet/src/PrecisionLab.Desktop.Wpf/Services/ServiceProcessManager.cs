using System.Diagnostics;
using System.IO;

namespace PrecisionLab.Desktop.Wpf.Services;

public static class ServiceProcessManager
{
    public static bool EnsureStarted(string? dataDirectory = null)
    {
        string executable = Path.Combine(
            AppContext.BaseDirectory,
            "PrecisionLab.Service.exe");
        if (!File.Exists(executable))
        {
            return false;
        }

        string arguments = string.IsNullOrWhiteSpace(dataDirectory)
            ? string.Empty
            : $"--data-dir \"{Path.GetFullPath(dataDirectory)}\"";
        using Process? process = Process.Start(
            new ProcessStartInfo(executable, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = AppContext.BaseDirectory,
            });
        return process is not null;
    }
}
