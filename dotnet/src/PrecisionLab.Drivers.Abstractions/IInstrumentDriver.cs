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

    ValueTask CancelPendingIoAsync(CancellationToken cancellationToken) =>
        ValueTask.CompletedTask;
}

public interface IInstrumentDriverFactory
{
    IInstrumentDriver Create(ChannelId channel, AcquisitionSettings settings);
}

public sealed record BurstAcquisitionSettings(
    int Count,
    TimeSpan Interval,
    TimeSpan Aperture,
    MeasurementFunction Function,
    string MeasurementRange);

public interface IBurstInstrumentDriver
{
    ValueTask<IReadOnlyList<Measurement>> AcquireBurstAsync(
        ChannelId channel,
        long firstSequence,
        BurstAcquisitionSettings settings,
        CancellationToken cancellationToken);
}

public interface IVisaMessageSession : IAsyncDisposable
{
    string Resource { get; }

    int TimeoutMilliseconds { get; set; }

    ValueTask ClearAsync(CancellationToken cancellationToken);

    ValueTask WriteAsync(string command, CancellationToken cancellationToken);

    ValueTask<string> ReadAsync(CancellationToken cancellationToken);

    ValueTask AbortAsync(CancellationToken cancellationToken);
}

public interface IVisaBackend
{
    ValueTask<IReadOnlyList<string>> DiscoverAsync(CancellationToken cancellationToken);

    ValueTask<IVisaMessageSession> OpenAsync(
        string resource,
        string backend,
        CancellationToken cancellationToken);
}
