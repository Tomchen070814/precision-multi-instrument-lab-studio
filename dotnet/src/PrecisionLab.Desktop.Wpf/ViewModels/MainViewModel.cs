using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Text;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PrecisionLab.Analysis;
using PrecisionLab.Contracts;
using PrecisionLab.Desktop.Wpf.Services;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.ViewModels;

public sealed partial class MainViewModel : ObservableObject, IAsyncDisposable
{
    private const int AnalysisPointLimit = 65_536;
    private readonly ControlPipeClient _controlClient;
    private readonly DataPipeClient _dataClient;
    private readonly ServiceProcessManager _serviceManager;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly Dictionary<ChannelId, Queue<Measurement>> _analysisPoints =
        Enum.GetValues<ChannelId>().ToDictionary(
            channel => channel,
            _ => new Queue<Measurement>());
    private Task? _statusTask;
    private int _analysisCounter;

    public MainViewModel(
        ControlPipeClient controlClient,
        DataPipeClient dataClient,
        ServiceProcessManager serviceManager,
        LocalizationService localization)
    {
        _controlClient = controlClient;
        _dataClient = dataClient;
        _serviceManager = serviceManager;
        Localization = localization;
        Channels =
        [
            new ChannelViewModel(ChannelId.A),
            new ChannelViewModel(ChannelId.B),
            new ChannelViewModel(ChannelId.C),
        ];
        _dataClient.MeasurementReceived += OnMeasurementReceived;
    }

    public event Action<Measurement>? MeasurementArrived;

    public LocalizationService Localization { get; }

    public ObservableCollection<ChannelViewModel> Channels { get; }

    public ObservableCollection<string> DiscoveredResources { get; } = [];

    public ObservableCollection<SessionSummary> Sessions { get; } = [];

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartSelectedCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopAllCommand))]
    [NotifyCanExecuteChangedFor(nameof(ScanResourcesCommand))]
    [NotifyCanExecuteChangedFor(nameof(RefreshSessionsCommand))]
    private bool _isConnected;

    [ObservableProperty]
    private string _serviceStatus = "Service disconnected";

    [ObservableProperty]
    private double _uiMemoryMb;

    [ObservableProperty]
    private double _serviceMemoryMb;

    [ObservableProperty]
    private string _systemMemoryText = "RAM —";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ExportSelectedSessionCommand))]
    private SessionSummary? _selectedSession;

    [ObservableProperty]
    private string _analysisText = "Waiting for measurement data.";

    private bool CanControlService() => IsConnected;

    private bool CanExportSession() => IsConnected && SelectedSession is not null;

    [RelayCommand]
    public async Task ConnectAsync()
    {
        try
        {
            ControlResponse response;
            try
            {
                response = await _controlClient.ConnectAsync(_lifetime.Token);
            }
            catch (TimeoutException)
            {
                _serviceManager.EnsureStarted();
                await Task.Delay(750, _lifetime.Token);
                response = await _controlClient.ConnectAsync(_lifetime.Token);
            }

            await _dataClient.ConnectAsync(_lifetime.Token);
            IsConnected = true;
            ServiceStatus = response.Message;
            Apply(response.Snapshot);
            if (_statusTask is null || _statusTask.IsCompleted)
            {
                _statusTask = PollStatusAsync(_lifetime.Token);
            }

            await RefreshSessionsAsync();
        }
        catch (Exception exception)
        {
            IsConnected = false;
            ServiceStatus = $"Connection failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanControlService))]
    private async Task StartSelectedAsync()
    {
        try
        {
            ChannelViewModel[] selected = Channels.Where(item => item.IsSelected).ToArray();
            if (selected.Length == 0)
            {
                throw new InvalidOperationException("Select at least one channel.");
            }

            var settings = selected.ToDictionary(
                item => item.Channel,
                item => item.BuildSettings());
            ControlResponse response = await _controlClient.StartAsync(
                selected.Select(item => item.Channel).ToArray(),
                settings,
                _lifetime.Token);
            ServiceStatus = "Selected channels started.";
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
            ServiceStatus = "All channels stopped after durable pipeline drain.";
            Apply(response.Snapshot);
            await RefreshSessionsAsync();
        }
        catch (Exception exception)
        {
            ServiceStatus = $"Stop failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanControlService))]
    private async Task ScanResourcesAsync()
    {
        try
        {
            ControlResponse response =
                await _controlClient.DiscoverResourcesAsync(_lifetime.Token);
            DiscoveredResources.Clear();
            foreach (string resource in response.Resources ?? [])
            {
                DiscoveredResources.Add(resource);
            }

            ServiceStatus = $"VISA scan found {DiscoveredResources.Count} resources.";
        }
        catch (Exception exception)
        {
            ServiceStatus = $"VISA scan failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanControlService))]
    private async Task RefreshSessionsAsync()
    {
        try
        {
            ControlResponse response =
                await _controlClient.ListSessionsAsync(500, _lifetime.Token);
            Guid? selectedId = SelectedSession?.Id;
            Sessions.Clear();
            foreach (SessionSummary session in response.Sessions ?? [])
            {
                Sessions.Add(session);
            }

            SelectedSession = Sessions.FirstOrDefault(item => item.Id == selectedId) ??
                Sessions.FirstOrDefault();
        }
        catch (Exception exception)
        {
            ServiceStatus = $"Session refresh failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanExportSession))]
    private async Task ExportSelectedSessionAsync()
    {
        if (SelectedSession is null)
        {
            return;
        }

        try
        {
            string directory = EnsureExportDirectory();
            string path = Path.Combine(
                directory,
                $"session-{SelectedSession.Id:D}.csv");
            ControlResponse response = await _controlClient.ExportSessionCsvAsync(
                SelectedSession.Id,
                path,
                _lifetime.Token);
            ServiceStatus = $"CSV exported: {response.OutputPath}";
        }
        catch (Exception exception)
        {
            ServiceStatus = $"CSV export failed: {exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanControlService))]
    private async Task ExportDiagnosticsAsync()
    {
        try
        {
            string path = Path.Combine(
                EnsureExportDirectory(),
                $"diagnostic-{DateTimeOffset.Now:yyyyMMdd-HHmmss}.zip");
            ControlResponse response = await _controlClient.ExportDiagnosticsAsync(
                path,
                Localization.CurrentLanguage,
                _lifetime.Token);
            ServiceStatus = $"Diagnostic ZIP exported: {response.OutputPath}";
        }
        catch (Exception exception)
        {
            ServiceStatus = $"Diagnostic export failed: {exception.Message}";
        }
    }

    [RelayCommand]
    private void ToggleLanguage() => Localization.Toggle();

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
                            $"Service disconnected; acquisition continues independently: " +
                            exception.Message;
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
                Queue<Measurement> points = _analysisPoints[measurement.Channel];
                points.Enqueue(measurement);
                while (points.Count > AnalysisPointLimit)
                {
                    points.Dequeue();
                }

                _analysisCounter++;
                if (_analysisCounter % 20 == 0)
                {
                    UpdateAnalysis();
                }

                MeasurementArrived?.Invoke(measurement);
            });
    }

    private void UpdateAnalysis()
    {
        var text = new StringBuilder();
        foreach ((ChannelId channel, Queue<Measurement> measurements) in _analysisPoints)
        {
            if (measurements.Count < 2)
            {
                continue;
            }

            Measurement[] snapshot = measurements.ToArray();
            double[] values = snapshot.Select(item => item.Value).ToArray();
            double[] elapsed =
                snapshot.Select(item => item.Elapsed.TotalSeconds).ToArray();
            StatisticsResult statistics = StatisticsAnalyzer.Describe(values, elapsed);
            LinearFitResult trend = StatisticsAnalyzer.LinearFit(elapsed, values);
            text.AppendLine(
                $"{channel} · n={statistics.Count:N0} · mean={statistics.Mean:G12} " +
                $"{snapshot[^1].Unit.Symbol()} · σ={statistics.StandardDeviation:G6} · " +
                $"RMS={statistics.Rms:G12} · drift={trend.DriftPerHour:G6}/h");

            if (snapshot.Length >= 32)
            {
                double samplePeriod = SpectrumAnalyzer.EstimateSamplePeriod(elapsed);
                SpectrumResult spectrum =
                    SpectrumAnalyzer.Spectrum(values, samplePeriod);
                int peak = 0;
                for (int index = 1; index < spectrum.Amplitude.Length; index++)
                {
                    if (spectrum.Amplitude[index] > spectrum.Amplitude[peak])
                    {
                        peak = index;
                    }
                }

                AllanResult allan =
                    SpectrumAnalyzer.AllanDeviation(values, samplePeriod);
                if (spectrum.Amplitude.Length > 0)
                {
                    text.AppendLine(
                        $"    FFT peak={spectrum.Frequency[peak]:G6} Hz / " +
                        $"{spectrum.Amplitude[peak]:G6}; " +
                        $"ASD bins={spectrum.Asd.Length}; Allan points={allan.Tau.Length}");
                }
            }
        }

        AnalysisText = text.Length == 0 ? "Waiting for measurement data." : text.ToString();
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
            snapshot.ServiceVersion;
        foreach (ChannelSnapshot channelSnapshot in snapshot.Channels)
        {
            Channels.Single(channel => channel.Channel == channelSnapshot.Channel)
                .Apply(channelSnapshot);
        }
    }

    private static string EnsureExportDirectory()
    {
        string directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "PrecisionLab",
            "Exports");
        Directory.CreateDirectory(directory);
        return directory;
    }
}
