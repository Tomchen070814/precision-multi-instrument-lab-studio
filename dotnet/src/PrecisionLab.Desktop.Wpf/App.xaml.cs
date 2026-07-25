using System.Windows;
using PrecisionLab.Desktop.Wpf.Services;
using PrecisionLab.Desktop.Wpf.ViewModels;

namespace PrecisionLab.Desktop.Wpf;

public partial class App : Application
{
    private MainViewModel? _viewModel;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        _viewModel = new MainViewModel(new ControlPipeClient(), new DataPipeClient());
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
}
