using CommunityToolkit.Mvvm.ComponentModel;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.ViewModels;

public sealed partial class ChannelViewModel : ObservableObject
{
    public ChannelViewModel(ChannelId channel)
    {
        Channel = channel;
    }

    public ChannelId Channel { get; }

    [ObservableProperty]
    private string _state = ChannelState.Stopped.ToString();

    [ObservableProperty]
    private string _latestReading = "—";

    [ObservableProperty]
    private string _instrument = "Not configured";

    [ObservableProperty]
    private string _resource = "—";

    [ObservableProperty]
    private long _sampleCount;

    [ObservableProperty]
    private string? _error;

    public void Apply(ChannelSnapshot snapshot)
    {
        State = snapshot.State.ToString();
        Instrument =
            $"{snapshot.Model} · {snapshot.Function} · {snapshot.Unit.Symbol()}";
        Resource = snapshot.Resource;
        SampleCount = snapshot.SampleCount;
        Error = snapshot.Error;
        if (snapshot.LastValue is double value)
        {
            LatestReading = $"{value:G12} {snapshot.Unit.Symbol()}";
        }
    }

    public void Apply(Measurement measurement)
    {
        LatestReading = $"{measurement.Value:G12} {measurement.Unit.Symbol()}";
        SampleCount = Math.Max(SampleCount, measurement.Sequence + 1);
    }
}
