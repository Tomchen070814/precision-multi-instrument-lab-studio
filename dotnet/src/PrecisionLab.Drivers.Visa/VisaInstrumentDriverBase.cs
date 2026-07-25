using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Visa;

public abstract class VisaInstrumentDriverBase : IInstrumentDriver
{
    private readonly IVisaBackend _backend;
    private readonly SemaphoreSlim _busLock;
    private readonly TimeProvider _timeProvider;
    private long _startedTimestamp;
    private bool _disposed;

    protected VisaInstrumentDriverBase(
        InstrumentModel model,
        AcquisitionSettings settings,
        IVisaBackend backend,
        TimeProvider? timeProvider = null)
    {
        InstrumentModel = model;
        Settings = settings.Validate();
        _backend = backend;
        _timeProvider = timeProvider ?? TimeProvider.System;
        _busLock = VisaDriverUtilities.BusLock(settings.Resource);
    }

    public InstrumentModel InstrumentModel { get; }

    public string Resource => Settings.Resource;

    protected AcquisitionSettings Settings { get; set; }

    protected IVisaMessageSession? Session { get; private set; }

    protected InstrumentIdentity? Identity { get; set; }

    protected TimeSpan Elapsed => _timeProvider.GetElapsedTime(_startedTimestamp);

    public abstract ValueTask<InstrumentIdentity> ConnectAsync(
        CancellationToken cancellationToken);

    public abstract ValueTask ConfigureAsync(
        AcquisitionSettings settings,
        CancellationToken cancellationToken);

    public abstract ValueTask<Measurement> ReadAsync(
        ChannelId channel,
        long sequence,
        TimeSpan elapsed,
        bool includeTemperature,
        CancellationToken cancellationToken);

    public virtual async ValueTask DisconnectAsync(CancellationToken cancellationToken)
    {
        IVisaMessageSession? session = Session;
        Session = null;
        if (session is not null)
        {
            await session.DisposeAsync().ConfigureAwait(false);
        }
    }

    public async ValueTask CancelPendingIoAsync(CancellationToken cancellationToken)
    {
        if (Session is not null)
        {
            await Session.AbortAsync(cancellationToken).ConfigureAwait(false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        await DisconnectAsync(CancellationToken.None).ConfigureAwait(false);
        GC.SuppressFinalize(this);
    }

    protected async ValueTask OpenSessionAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        Session = await _backend.OpenAsync(
            Settings.Resource,
            Settings.VisaBackend,
            cancellationToken).ConfigureAwait(false);
        _startedTimestamp = _timeProvider.GetTimestamp();
    }

    protected async ValueTask WriteAsync(
        string command,
        CancellationToken cancellationToken)
    {
        IVisaMessageSession session = RequireSession();
        await _busLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await session.WriteAsync(command, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is not InstrumentDriverException)
        {
            throw new InstrumentDriverException(
                $"Command '{command}' failed on {Resource}: {exception.Message}",
                exception);
        }
        finally
        {
            _busLock.Release();
        }
    }

    protected async ValueTask<string> QueryAsync(
        string command,
        CancellationToken cancellationToken)
    {
        IVisaMessageSession session = RequireSession();
        await _busLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await session.WriteAsync(command, cancellationToken).ConfigureAwait(false);
            return (await session.ReadAsync(cancellationToken).ConfigureAwait(false)).Trim();
        }
        catch (Exception exception) when (exception is not InstrumentDriverException)
        {
            throw new InstrumentDriverException(
                $"Query '{command}' failed on {Resource}: {exception.Message}",
                exception);
        }
        finally
        {
            _busLock.Release();
        }
    }

    protected IVisaMessageSession RequireSession() =>
        Session ?? throw new InstrumentDriverException(
            $"{InstrumentCatalog.Get(InstrumentModel).ShortName} is not connected.");

    protected static double FirstNumber(string payload, string command)
    {
        double[] values = VisaDriverUtilities.ParseNumbers(payload);
        return values.Length > 0
            ? values[0]
            : throw new InstrumentDriverException(
                $"Command '{command}' returned no numeric value.");
    }
}
