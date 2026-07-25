using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Builtin;

public sealed class BuiltinInstrumentDriverFactory : IInstrumentDriverFactory
{
    private readonly IInstrumentDriverFactory? _physicalFactory;

    public BuiltinInstrumentDriverFactory(IInstrumentDriverFactory? physicalFactory = null)
    {
        _physicalFactory = physicalFactory;
    }

    public IInstrumentDriver Create(ChannelId channel, AcquisitionSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        settings.Validate();

        if (settings.Resource.StartsWith("SIM::", StringComparison.OrdinalIgnoreCase))
        {
            return new SimulatorInstrumentDriver(channel, settings);
        }

        if (_physicalFactory is not null)
        {
            return _physicalFactory.Create(channel, settings);
        }

        InstrumentProtocol protocol = InstrumentCatalog.Get(settings.InstrumentModel).Protocol;
        throw new NotSupportedException(
            $"No live {protocol} provider is registered. Install a compatible " +
            "VISA 7.4+ implementation or use a SIM:: resource.");
    }
}
