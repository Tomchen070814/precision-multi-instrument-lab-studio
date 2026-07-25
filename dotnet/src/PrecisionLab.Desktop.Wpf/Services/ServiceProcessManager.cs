using System.Diagnostics;

namespace PrecisionLab.Desktop.Wpf.Services;

public sealed class ServiceProcessManager
{
    public bool EnsureStarted(string? dataDirectory = null)
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
