using PrecisionLab.Domain;

namespace PrecisionLab.Drivers.Abstractions;

public interface IInstrumentDriver : IAsyncDisposable
{
    InstrumentModel InstrumentModel { get; }

    string Resource { get; }

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
