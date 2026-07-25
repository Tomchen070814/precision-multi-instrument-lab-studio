using System.Diagnostics;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Builtin;

public sealed class SimulatorInstrumentDriver : IInstrumentDriver
{
    private readonly Random _random;
    private readonly Stopwatch _uptime = new();
    private AcquisitionSettings _settings;
    private bool _connected;

    public SimulatorInstrumentDriver(ChannelId channel, AcquisitionSettings settings)
    {
        _settings = settings.Validate();
        _random = new Random(3_458 + ((int)channel * 10_007));
    }

    public InstrumentModel InstrumentModel => _settings.InstrumentModel;

    public string Resource => _settings.Resource;

    public ValueTask<InstrumentIdentity> ConnectAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        InstrumentDescriptor descriptor = InstrumentCatalog.Get(InstrumentModel);
        _connected = true;
        _uptime.Restart();

        return ValueTask.FromResult(
            new InstrumentIdentity(
                InstrumentModel,
                $"{descriptor.Manufacturer.ToUpperInvariant()},{descriptor.ShortName} (SIMULATOR)",
                Resource,
                InstrumentModel == InstrumentModel.Keysight3458A ? "9.2,9.1" : "SIM-1.0",
                InstrumentModel == InstrumentModel.Keysight3458A ? "1" : string.Empty,
                50));
    }

    public ValueTask ConfigureAsync(
        AcquisitionSettings settings,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureConnected();
        _settings = settings.Validate();
        return ValueTask.CompletedTask;
    }

    public ValueTask<Measurement> ReadAsync(
        ChannelId channel,
        long sequence,
        TimeSpan elapsed,
        bool includeTemperature,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureConnected();

        double seconds = elapsed.TotalSeconds;
        double baseline = Baseline(_settings.Function);
        double scale = Math.Abs(baseline) > double.Epsilon ? Math.Abs(baseline) : 1;
        double nplcNoise = Math.Max(0.08, 1 / Math.Sqrt(Math.Max(_settings.Nplc, 1e-4)));
        double warmup = -5.5e-6 * scale * Math.Exp(-seconds / 100);
        double drift = 0.14e-6 * scale * seconds / 3_600;
        double hum = 0.65e-6 * scale * Math.Sin(2 * Math.PI * 0.37 * seconds);
        double slow = 1.8e-6 * scale * Math.Sin(2 * Math.PI * seconds / 95);
        double noise = NextGaussian() * 0.7e-6 * scale * nplcNoise;
        double temperature = 23 + (0.55 * (1 - Math.Exp(-seconds / 180)));
        temperature += 0.08 * Math.Sin(2 * Math.PI * seconds / 240);

        return ValueTask.FromResult(
            new Measurement(
                channel,
                sequence,
                DateTimeOffset.UtcNow,
                elapsed,
                baseline + warmup + drift + hum + slow + noise,
                _settings.Function.Unit(),
                includeTemperature ? temperature : null));
    }

    public ValueTask DisconnectAsync(CancellationToken cancellationToken)
    {
        _connected = false;
        _uptime.Stop();
        return ValueTask.CompletedTask;
    }

    public async ValueTask DisposeAsync()
    {
        await DisconnectAsync(CancellationToken.None).ConfigureAwait(false);
    }

    private static double Baseline(MeasurementFunction function) =>
        function switch
        {
            MeasurementFunction.DcVoltage => 10,
            MeasurementFunction.AcVoltage or MeasurementFunction.AcDcVoltage => 1,
            MeasurementFunction.Resistance2Wire
                or MeasurementFunction.Resistance4Wire => 10_000,
            MeasurementFunction.DcCurrent
                or MeasurementFunction.AcCurrent
                or MeasurementFunction.AcDcCurrent => 0.01,
            MeasurementFunction.Frequency => 10_000,
            MeasurementFunction.Period => 0.0001,
            MeasurementFunction.DigitizeDc or MeasurementFunction.DigitizeAc => 1,
            _ => throw new ArgumentOutOfRangeException(nameof(function)),
        };

    private double NextGaussian()
    {
        double u1 = 1 - _random.NextDouble();
        double u2 = 1 - _random.NextDouble();
        return Math.Sqrt(-2 * Math.Log(u1)) * Math.Cos(2 * Math.PI * u2);
    }

    private void EnsureConnected()
    {
        if (!_connected)
        {
            throw new InvalidOperationException("The simulated instrument is not connected.");
        }
    }
}
