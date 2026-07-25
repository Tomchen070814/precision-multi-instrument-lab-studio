using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Visa;

public sealed class VisaInstrumentDriverFactory : IInstrumentDriverFactory
{
    private readonly IVisaBackend _backend;
    private readonly TimeProvider _timeProvider;

    public VisaInstrumentDriverFactory(
        IVisaBackend backend,
        TimeProvider? timeProvider = null)
    {
        _backend = backend;
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public IInstrumentDriver Create(ChannelId channel, AcquisitionSettings settings)
    {
        _ = channel;
        ArgumentNullException.ThrowIfNull(settings);
        settings.Validate();
        return InstrumentCatalog.Get(settings.InstrumentModel).Protocol switch
        {
            InstrumentProtocol.HpIb3458A =>
                new Keysight3458ADriver(settings, _backend, _timeProvider),
            InstrumentProtocol.Ieee488Fluke8508A =>
                new Fluke8508ADriver(settings, _backend, _timeProvider),
            InstrumentProtocol.Scpi =>
                new ScpiDmmDriver(settings, _backend, _timeProvider),
            _ => throw new ArgumentOutOfRangeException(nameof(settings)),
        };
    }
}
