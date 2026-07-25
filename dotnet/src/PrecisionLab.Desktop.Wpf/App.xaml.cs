using System.Diagnostics.CodeAnalysis;
using System.Windows;
using PrecisionLab.Contracts;
using PrecisionLab.Desktop.Wpf.Services;
using PrecisionLab.Desktop.Wpf.ViewModels;

namespace PrecisionLab.Desktop.Wpf;

[SuppressMessage(
    "Design",
    "CA1001",
    Justification = "WPF owns the application lifetime; OnExit disposes the view model.")]
public partial class App : Application
{
    private MainViewModel? _viewModel;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Contains("--headless-smoke", StringComparer.OrdinalIgnoreCase))
        {
            int result = await RunHeadlessSmokeAsync().ConfigureAwait(true);
            Shutdown(result);
            return;
        }

        _viewModel = new MainViewModel(
            new ControlPipeClient(),
            new DataPipeClient(),
            new LocalizationService());
        var window = new MainWindow(_viewModel);
        MainWindow = window;
        window.Show();
        await _viewModel.ConnectAsync();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _viewModel?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        base.OnExit(e);
    }

    private static async Task<int> RunHeadlessSmokeAsync()
    {
        await using var client = new ControlPipeClient();
        try
        {
            try
            {
                await client.ConnectAsync(CancellationToken.None).ConfigureAwait(true);
            }
            catch (TimeoutException)
            {
                ServiceProcessManager.EnsureStarted();
                await Task.Delay(750).ConfigureAwait(true);
                await client.ConnectAsync(CancellationToken.None).ConfigureAwait(true);
            }

            ControlResponse response = await client.SnapshotAsync(
                CancellationToken.None).ConfigureAwait(true);
            return response.Snapshot?.ProtocolVersion == PipeNames.ProtocolVersion
                ? 0
                : 2;
        }
        catch
        {
            return 1;
        }
    }
}
