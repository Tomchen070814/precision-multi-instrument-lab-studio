using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Builtin;

public sealed class BuiltinInstrumentDriverFactory : IInstrumentDriverFactory
{
    public IInstrumentDriver Create(ChannelId channel, AcquisitionSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        settings.Validate();

        if (settings.Resource.StartsWith("SIM::", StringComparison.OrdinalIgnoreCase))
        {
            return new SimulatorInstrumentDriver(channel, settings);
        }

        InstrumentProtocol protocol = InstrumentCatalog.Get(settings.InstrumentModel).Protocol;
        throw new NotSupportedException(
            $"The phase-one branch intentionally has no live {protocol} provider. " +
            "Use a SIM:: resource until the protocol transcript tests are migrated.");
    }
}
