using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Builtin;

public sealed class DigitalTwinDriverFactory : IInstrumentDriverFactory
{
    public IInstrumentDriver Create(ChannelId channel, AcquisitionSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        settings.Validate();
        if (!settings.Resource.StartsWith("SIM::", StringComparison.OrdinalIgnoreCase))
        {
            throw new NotSupportedException(
                $"Live resource '{settings.Resource}' is disabled in phase one. " +
                "A protocol-conformance driver must be registered before real I/O is allowed.");
        }

        InstrumentDescriptor descriptor = InstrumentCatalog.Get(settings.InstrumentModel);
        if (!descriptor.SupportedFunctions.Contains(settings.Function))
        {
            throw new NotSupportedException(
                $"{descriptor.Manufacturer} {descriptor.ModelName} does not support " +
                $"{settings.Function} in the capability catalog.");
        }

        return new DigitalTwinDriver(channel, descriptor, settings.Resource);
    }
}
