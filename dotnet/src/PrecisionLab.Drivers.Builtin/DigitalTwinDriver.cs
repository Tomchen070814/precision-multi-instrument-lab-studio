using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Builtin;

internal sealed class DigitalTwinDriver : IInstrumentDriver
{
    private readonly ChannelId _channel;
    private readonly InstrumentDescriptor _descriptor;
    private readonly string _resource;
    private readonly Random _random;
    private AcquisitionSettings? _settings;
    private bool _connected;

    public DigitalTwinDriver(
        ChannelId channel,
        InstrumentDescriptor descriptor,
        string resource)
    {
        _channel = channel;
        _descriptor = descriptor;
        _resource = resource;
        _random = new Random(HashCode.Combine(channel, descriptor.Model, 0x3458));
    }

    public ValueTask<InstrumentIdentity> ConnectAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        _connected = true;
        return ValueTask.FromResult(
            new InstrumentIdentity(
                _descriptor.Model,
                _descriptor.Manufacturer,
                _descriptor.ModelName,
                _resource,
                InstrumentProtocol.DigitalTwin));
    }

    public ValueTask ConfigureAsync(
        AcquisitionSettings settings,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!_connected)
        {
            throw new InvalidOperationException("The digital twin is not connected.");
        }

        settings.Validate();
        if (!_descriptor.SupportedFunctions.Contains(settings.Function))
        {
            throw new NotSupportedException(
                $"{_descriptor.ModelName} does not support {settings.Function}.");
        }

        _settings = settings;
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
        if (!_connected || _settings is null)
        {
            throw new InvalidOperationException("The digital twin is not configured.");
        }

        if (channel != _channel)
        {
            throw new InvalidOperationException(
                $"Driver for channel {_channel} cannot emit channel {channel}.");
        }

        double phase = (int)_channel * Math.PI / 3;
        double center = _channel switch
        {
            ChannelId.A => 0,
            ChannelId.B => 1,
            ChannelId.C => -1,
            _ => 0,
        };
        double value =
            center +
            (0.001 * Math.Sin((2 * Math.PI * 0.2 * elapsed.TotalSeconds) + phase)) +
            (sequence * 2e-10) +
            (NextGaussian() * 2e-6);
        double? temperature =
            includeTemperature && _descriptor.SupportsInternalTemperature
                ? 23.0 + (0.2 * Math.Sin(2 * Math.PI * elapsed.TotalSeconds / 300))
                : null;

        return ValueTask.FromResult(
            new Measurement(
                channel,
                sequence,
                DateTimeOffset.UtcNow,
                elapsed,
                value,
                _settings.Function.Unit(),
                temperature));
    }

    public ValueTask DisconnectAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        _connected = false;
        _settings = null;
        return ValueTask.CompletedTask;
    }

    public ValueTask DisposeAsync()
    {
        _connected = false;
        _settings = null;
        return ValueTask.CompletedTask;
    }

    private double NextGaussian()
    {
        double u1 = 1 - _random.NextDouble();
        double u2 = 1 - _random.NextDouble();
        return Math.Sqrt(-2 * Math.Log(u1)) * Math.Cos(2 * Math.PI * u2);
    }
}
