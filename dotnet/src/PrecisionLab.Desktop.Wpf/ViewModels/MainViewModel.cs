using System.Collections.ObjectModel;
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
    private readonly SynchronizationContext _uiContext;
    private Task? _pollTask;

    [ObservableProperty]
    private string _serviceStatus = "Service offline";

    [ObservableProperty]
    private double _uiMemoryMb;

    [ObservableProperty]
    private double _serviceMemoryMb;

    [ObservableProperty]
    private bool _isConnected;

    public MainViewModel(ControlPipeClient controlClient, DataPipeClient dataClient)
    {
        _controlClient = controlClient;
        _dataClient = dataClient;
        _uiContext = SynchronizationContext.Current
            ?? throw new InvalidOperationException("MainViewModel must be created on the UI thread.");
        Channels =
        [
            new ChannelViewModel(ChannelId.A),
            new ChannelViewModel(ChannelId.B),
            new ChannelViewModel(ChannelId.C),
        ];
        _dataClient.MeasurementReceived += OnMeasurementReceived;
    }

    public ObservableCollection<ChannelViewModel> Channels { get; }

    public event Action<Measurement>? MeasurementArrived;

    [RelayCommand]
    public async Task ConnectAsync()
    {
        try
        {
            ControlResponse response = await _controlClient.SendAsync(
                new ControlRequest(ControlOperations.Hello),
                _lifetime.Token);
            ApplyResponse(response);
            _dataClient.Start();
            _pollTask ??= Task.Run(
                () => PollSnapshotsAsync(_lifetime.Token),
                CancellationToken.None);
        }
        catch (Exception exception) when (
            exception is IOException or OperationCanceledException or TimeoutException)
        {
            IsConnected = false;
            ServiceStatus = "Service offline · start PrecisionLab.Service.exe";
        }
    }

    [RelayCommand]
    private async Task StartAllAsync()
    {
        ControlResponse response = await _controlClient.SendAsync(
            new ControlRequest(
                ControlOperations.Start,
                [ChannelId.A, ChannelId.B, ChannelId.C]),
            _lifetime.Token);
        ApplyResponse(response);
    }

    [RelayCommand]
    private async Task StopAllAsync()
    {
        ControlResponse response = await _controlClient.SendAsync(
            new ControlRequest(ControlOperations.StopAll),
            _lifetime.Token);
        ApplyResponse(response);
    }

    public async ValueTask DisposeAsync()
    {
        _dataClient.MeasurementReceived -= OnMeasurementReceived;
        _lifetime.Cancel();
        if (_pollTask is not null)
        {
            try
            {
                await _pollTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Normal window shutdown.
            }
        }

        await _dataClient.DisposeAsync().ConfigureAwait(false);
        _lifetime.Dispose();
    }

    private async Task PollSnapshotsAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));
        while (await timer.WaitForNextTickAsync(cancellationToken).ConfigureAwait(false))
        {
            try
            {
                ControlResponse response = await _controlClient.SendAsync(
                    new ControlRequest(ControlOperations.Snapshot),
                    cancellationToken).ConfigureAwait(false);
                _uiContext.Post(_ => ApplyResponse(response), null);
            }
            catch (Exception exception) when (
                exception is IOException or OperationCanceledException or TimeoutException)
            {
                if (!cancellationToken.IsCancellationRequested)
                {
                    _uiContext.Post(
                        _ =>
                        {
                            IsConnected = false;
                            ServiceStatus = "Service reconnecting…";
                        },
                        null);
                }
            }
        }
    }

    private void ApplyResponse(ControlResponse response)
    {
        UiMemoryMb = Environment.WorkingSet / 1_048_576d;
        IsConnected = response.Success;
        ServiceStatus = response.Success ? "Service connected" : response.Message;
        if (response.Snapshot is not ServiceSnapshot snapshot)
        {
            return;
        }

        ServiceMemoryMb = snapshot.ServiceWorkingSetBytes / 1_048_576d;
        foreach (ChannelSnapshot channel in snapshot.Channels)
        {
            Channels.Single(item => item.Channel == channel.Channel).Apply(channel);
        }
    }

    private void OnMeasurementReceived(Measurement measurement)
    {
        _uiContext.Post(
            _ =>
            {
                Channels.Single(item => item.Channel == measurement.Channel).Apply(measurement);
                MeasurementArrived?.Invoke(measurement);
            },
            null);
    }
}
