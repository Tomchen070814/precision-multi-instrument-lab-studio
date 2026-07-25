using Ivi.Visa;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Visa;

public sealed class IviVisaBackend : IVisaBackend
{
    public ValueTask<IReadOnlyList<string>> DiscoverAsync(
        CancellationToken cancellationToken) =>
        new(Task.Run<IReadOnlyList<string>>(
            () => GlobalResourceManager.Find("?*").ToArray(),
            cancellationToken));

    public async ValueTask<IVisaMessageSession> OpenAsync(
        string resource,
        string backend,
        CancellationToken cancellationToken)
    {
        if (!string.IsNullOrWhiteSpace(backend))
        {
            throw new NotSupportedException(
                "VISA.NET selects its vendor backend through the IVI conflict manager. " +
                "A PyVISA-style backend path is not supported.");
        }

        IVisaSession visaSession = await Task.Run(
            () => GlobalResourceManager.Open(
                resource,
                AccessModes.NoLock,
                5_000),
            cancellationToken).ConfigureAwait(false);
        if (visaSession is not IMessageBasedSession messageSession)
        {
            visaSession.Dispose();
            throw new InstrumentDriverException(
                $"VISA resource '{resource}' is not message based.");
        }

        messageSession.TerminationCharacterEnabled = true;
        return new IviMessageSession(resource, messageSession);
    }

    private sealed class IviMessageSession : IVisaMessageSession
    {
        private IMessageBasedSession? _session;

        public IviMessageSession(string resource, IMessageBasedSession session)
        {
            Resource = resource;
            _session = session;
        }

        public string Resource { get; }

        public int TimeoutMilliseconds
        {
            get => RequireSession().TimeoutMilliseconds;
            set => RequireSession().TimeoutMilliseconds = value;
        }

        public ValueTask ClearAsync(CancellationToken cancellationToken) =>
            RunAsync(session => session.Clear(), cancellationToken);

        public ValueTask WriteAsync(
            string command,
            CancellationToken cancellationToken) =>
            RunAsync(session => session.FormattedIO.WriteLine(command), cancellationToken);

        public async ValueTask<string> ReadAsync(CancellationToken cancellationToken) =>
            await Task.Run(
                () => RequireSession().FormattedIO.ReadLine(),
                cancellationToken).ConfigureAwait(false);

        public ValueTask AbortAsync(CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            IMessageBasedSession? session = Interlocked.Exchange(ref _session, null);
            session?.Dispose();
            return ValueTask.CompletedTask;
        }

        public ValueTask DisposeAsync()
        {
            IMessageBasedSession? session = Interlocked.Exchange(ref _session, null);
            session?.Dispose();
            return ValueTask.CompletedTask;
        }

        private async ValueTask RunAsync(
            Action<IMessageBasedSession> action,
            CancellationToken cancellationToken)
        {
            await Task.Run(
                () => action(RequireSession()),
                cancellationToken).ConfigureAwait(false);
        }

        private IMessageBasedSession RequireSession() =>
            _session ?? throw new ObjectDisposedException(nameof(IviMessageSession));
    }
}
