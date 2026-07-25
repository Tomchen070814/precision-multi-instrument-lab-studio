using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PrecisionLab.Contracts;
using PrecisionLab.Desktop.Wpf.Services;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.ViewModels;

public sealed partial class MainViewModel : ObservableObject, IAsyncDisposable
{
    private readonly ControlPipeClient _controlClient;
    private readonly DataPipeClient _dataClient;
    private readonly CancellationTokenSource _lifetime = new();
    private Task? _statusTask;

    public MainViewModel(
        ControlPipeClient controlClient,
        DataPipeClient dataClient)
    {
        _controlClient = controlClient;
        _dataClient = dataClient;
        Channels =
        [
            new ChannelViewModel(ChannelId.A),
            new ChannelViewModel(ChannelId.B),
            new ChannelViewModel(ChannelId.C),
        ];
        _dataClient.MeasurementReceived += OnMeasurementReceived;
    }

    public event Action<Measurement>? MeasurementArrived;

    public ObservableCollection<ChannelViewModel> Channels { get; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartAllCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopAllCommand))]
    private bool _isConnected;

    [ObservableProperty]
    private string _serviceStatus = "Service disconnected";

    [ObservableProperty]
    private double _uiMemoryMb;

    [ObservableProperty]
    private double _serviceMemoryMb;

    [ObservableProperty]
    private string _systemMemoryText = "RAM —";

    private bool CanControlService() => IsConnected;

    [RelayCommand]
    public async Task ConnectAsync()
    {
        try
        {
            ControlResponse response = await _controlClient.ConnectAsync(_lifetime.Token);
            await _dataClient.ConnectAsync(_lifetime.Token);
            IsConnected = true;
            ServiceStatus = response.Message;
            Apply(response.Snapshot);
            _statusTask ??= PollStatusAsync(_lifetime.Token);
        }
        catch (Exception exception)
        {
            IsConnected = false;
            ServiceStatus = $"Connection failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanControlService))]
    private async Task StartAllAsync()
    {
        try
        {
            ControlResponse response =
                await _controlClient.StartAllAsync(_lifetime.Token);
            ServiceStatus = "A/B/C digital twins running";
            Apply(response.Snapshot);
        }
        catch (Exception exception)
        {
            ServiceStatus = $"Start failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanControlService))]
    private async Task StopAllAsync()
    {
        try
        {
            ControlResponse response =
                await _controlClient.StopAllAsync(_lifetime.Token);
            ServiceStatus = "All channels stopped after durable pipeline drain";
            Apply(response.Snapshot);
        }
        catch (Exception exception)
        {
            ServiceStatus = $"Stop failed: {exception.Message}";
        }
    }

    public async ValueTask DisposeAsync()
    {
        _lifetime.Cancel();
        _dataClient.MeasurementReceived -= OnMeasurementReceived;
        await _dataClient.DisposeAsync().ConfigureAwait(false);
        await _controlClient.DisposeAsync().ConfigureAwait(false);
        if (_statusTask is not null)
        {
            try
            {
                await _statusTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        _lifetime.Dispose();
    }

    private async Task PollStatusAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));
        while (await timer.WaitForNextTickAsync(cancellationToken).ConfigureAwait(false))
        {
            try
            {
                ControlResponse response =
                    await _controlClient.SnapshotAsync(cancellationToken).ConfigureAwait(false);
                await Application.Current.Dispatcher.InvokeAsync(
                    () =>
                    {
                        Apply(response.Snapshot);
                        IsConnected = true;
                    });
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exception)
            {
                await Application.Current.Dispatcher.InvokeAsync(
                    () =>
                    {
                        IsConnected = false;
                        ServiceStatus =
                            $"Service disconnected; acquisition state unknown: {exception.Message}";
                    });
                return;
            }
        }
    }

    private void OnMeasurementReceived(Measurement measurement)
    {
        _ = Application.Current.Dispatcher.InvokeAsync(
            () =>
            {
                Channels.Single(channel => channel.Channel == measurement.Channel)
                    .Apply(measurement);
                MeasurementArrived?.Invoke(measurement);
            });
    }

    private void Apply(ServiceSnapshot? snapshot)
    {
        UiMemoryMb = Process.GetCurrentProcess().WorkingSet64 / 1_048_576.0;
        SystemMemoryText = MemoryMetrics.SystemLoadPercent() is double load
            ? $"RAM {load:F0}%"
            : "RAM —";
        if (snapshot is null)
        {
            return;
        }

        ServiceMemoryMb = snapshot.ServiceWorkingSetBytes / 1_048_576.0;
        ServiceStatus =
            $"Service PID {snapshot.ServiceProcessId} · protocol {snapshot.ProtocolVersion} · " +
            $"{snapshot.ServiceVersion}";
        foreach (ChannelSnapshot channelSnapshot in snapshot.Channels)
        {
            Channels.Single(channel => channel.Channel == channelSnapshot.Channel)
                .Apply(channelSnapshot);
        }
    }
}
