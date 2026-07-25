using CommunityToolkit.Mvvm.ComponentModel;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.ViewModels;

public sealed partial class ChannelViewModel : ObservableObject
{
    [ObservableProperty]
    private string _state = ChannelState.Stopped.ToString();

    [ObservableProperty]
    private string _instrument = string.Empty;

    [ObservableProperty]
    private string _resource = string.Empty;

    [ObservableProperty]
    private string _function = string.Empty;

    [ObservableProperty]
    private string _latestReading = "—";

    [ObservableProperty]
    private long _sampleCount;

    [ObservableProperty]
    private string? _error;

    public ChannelViewModel(ChannelId channel)
    {
        Channel = channel;
    }

    public ChannelId Channel { get; }

    public void Apply(ChannelSnapshot snapshot)
    {
        State = snapshot.State.ToString();
        InstrumentDescriptor descriptor = InstrumentCatalog.Get(snapshot.InstrumentModel);
        Instrument = $"{descriptor.Manufacturer} {descriptor.ShortName}";
        Resource = snapshot.Resource;
        Function = snapshot.Function.ToString();
        SampleCount = snapshot.SampleCount;
        Error = snapshot.Error;
        if (snapshot.LastValue is double value)
        {
            LatestReading = $"{value:G12} {snapshot.Unit.Symbol()}";
        }
    }

    public void Apply(Measurement measurement)
    {
        SampleCount = Math.Max(SampleCount, measurement.Sequence + 1);
        LatestReading = $"{measurement.Value:G12} {measurement.Unit.Symbol()}";
    }
}
