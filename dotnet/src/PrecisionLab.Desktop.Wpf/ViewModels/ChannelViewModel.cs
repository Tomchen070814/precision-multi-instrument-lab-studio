using CommunityToolkit.Mvvm.ComponentModel;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.ViewModels;

public sealed partial class ChannelViewModel : ObservableObject
{
    public ChannelViewModel(ChannelId channel)
    {
        Channel = channel;
        InstrumentModel = channel switch
        {
            ChannelId.A => InstrumentModel.Keysight3458A,
            ChannelId.B => InstrumentModel.Keysight34470A,
            _ => InstrumentModel.Fluke8588A,
        };
        Resource = $"SIM::{InstrumentModel}";
    }

    public ChannelId Channel { get; }

    public IReadOnlyList<InstrumentModel> InstrumentModels { get; } =
        InstrumentCatalog.All.Select(item => item.Model).ToArray();

    public IReadOnlyList<MeasurementFunction> Functions { get; } =
        Enum.GetValues<MeasurementFunction>();

    public IReadOnlyList<string> AutozeroModes { get; } = ["ON", "OFF", "ONCE"];

    public IReadOnlyList<StorageDurability> DurabilityModes { get; } =
        Enum.GetValues<StorageDurability>();

    [ObservableProperty]
    private bool _isSelected = true;

    [ObservableProperty]
    private InstrumentModel _instrumentModel;

    [ObservableProperty]
    private MeasurementFunction _function = MeasurementFunction.DcVoltage;

    [ObservableProperty]
    private string _measurementRange = "AUTO";

    [ObservableProperty]
    private double _nplc = 10;

    [ObservableProperty]
    private int _digits = 8;

    [ObservableProperty]
    private string _autozero = "ON";

    [ObservableProperty]
    private double _intervalMilliseconds = 250;

    [ObservableProperty]
    private double _burstApertureMicroseconds = 1;

    [ObservableProperty]
    private StorageDurability _durability = StorageDurability.Maximum;

    [ObservableProperty]
    private string _maxSamples = string.Empty;

    [ObservableProperty]
    private string _state = ChannelState.Stopped.ToString();

    [ObservableProperty]
    private string _latestReading = "—";

    [ObservableProperty]
    private string _instrument = "Not configured";

    [ObservableProperty]
    private string _resource = "SIM::3458A";

    [ObservableProperty]
    private long _sampleCount;

    [ObservableProperty]
    private string? _error;

    partial void OnInstrumentModelChanged(InstrumentModel value)
    {
        if (Resource.StartsWith("SIM::", StringComparison.OrdinalIgnoreCase))
        {
            Resource = $"SIM::{value}";
        }

        InstrumentDescriptor descriptor = InstrumentCatalog.Get(value);
        if (!descriptor.Supports(Function))
        {
            Function = descriptor.SupportedFunctions[0];
        }
    }

    public AcquisitionSettings BuildSettings()
    {
        long? maximum = null;
        if (!string.IsNullOrWhiteSpace(MaxSamples))
        {
            if (!long.TryParse(MaxSamples, out long parsed) || parsed <= 0)
            {
                throw new ArgumentException(
                    $"Channel {Channel}: maximum samples must be a positive integer.");
            }

            maximum = parsed;
        }

        return new AcquisitionSettings
        {
            InstrumentModel = InstrumentModel,
            Function = Function,
            Resource = Resource.Trim(),
            MeasurementRange = MeasurementRange.Trim(),
            Nplc = Nplc,
            Digits = Digits,
            Autozero = Autozero,
            SampleInterval = TimeSpan.FromMilliseconds(IntervalMilliseconds),
            BurstAperture = TimeSpan.FromMicroseconds(BurstApertureMicroseconds),
            MaxSamples = maximum,
            Durability = Durability,
        }.Validate();
    }

    public void Apply(ChannelSnapshot snapshot)
    {
        State = snapshot.State.ToString();
        InstrumentModel = snapshot.InstrumentModel;
        Function = snapshot.Function;
        Instrument =
            $"{snapshot.InstrumentModel} · {snapshot.Function} · {snapshot.Unit.Symbol()}";
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
