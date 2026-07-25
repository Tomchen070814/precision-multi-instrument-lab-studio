using PrecisionLab.Domain;

namespace PrecisionLab.Drivers.Abstractions;

public sealed record InstrumentDescriptor(
    InstrumentModel Model,
    string Manufacturer,
    string ModelName,
    InstrumentProtocol LiveProtocol,
    IReadOnlySet<MeasurementFunction> SupportedFunctions,
    bool SupportsInternalTemperature);

public interface IInstrumentDriver : IAsyncDisposable
{
    ValueTask<InstrumentIdentity> ConnectAsync(CancellationToken cancellationToken);

    ValueTask ConfigureAsync(
        AcquisitionSettings settings,
        CancellationToken cancellationToken);

    ValueTask<Measurement> ReadAsync(
        ChannelId channel,
        long sequence,
        TimeSpan elapsed,
        bool includeTemperature,
        CancellationToken cancellationToken);

    ValueTask DisconnectAsync(CancellationToken cancellationToken);
}

public interface IInstrumentDriverFactory
{
    IInstrumentDriver Create(ChannelId channel, AcquisitionSettings settings);
}
