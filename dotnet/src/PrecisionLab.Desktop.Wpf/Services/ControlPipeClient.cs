using System.IO.Pipes;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.Services;

public sealed class ControlPipeClient : IAsyncDisposable
{
    private readonly SemaphoreSlim _operationLock = new(1, 1);
    private NamedPipeClientStream? _pipe;

    public bool IsConnected => _pipe?.IsConnected == true;

    public async Task<ControlResponse> ConnectAsync(CancellationToken cancellationToken)
    {
        if (!IsConnected)
        {
            if (_pipe is not null)
            {
                await _pipe.DisposeAsync().ConfigureAwait(false);
            }

            _pipe = new NamedPipeClientStream(
                ".",
                PipeNames.Control,
                PipeDirection.InOut,
                PipeOptions.Asynchronous);
            await _pipe.ConnectAsync(3_000, cancellationToken).ConfigureAwait(false);
        }

        return await SendAsync(
            new ControlRequest(ControlOperations.Hello),
            cancellationToken).ConfigureAwait(false);
    }

    public Task<ControlResponse> SnapshotAsync(CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(ControlOperations.Snapshot),
            cancellationToken);

    public Task<ControlResponse> StartAsync(
        IReadOnlyList<ChannelId> channels,
        IReadOnlyDictionary<ChannelId, AcquisitionSettings> settings,
        CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(
                ControlOperations.Start,
                channels,
                settings),
            cancellationToken);

    public Task<ControlResponse> StopAllAsync(CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(ControlOperations.StopAll),
            cancellationToken);

    public Task<ControlResponse> DiscoverResourcesAsync(
        CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(ControlOperations.DiscoverResources),
            cancellationToken);

    public Task<ControlResponse> ListSessionsAsync(
        int limit,
        CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(ControlOperations.ListSessions, Limit: limit),
            cancellationToken);

    public Task<ControlResponse> ReadSessionWindowAsync(
        Guid sessionId,
        long firstSequence,
        int limit,
        CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(
                ControlOperations.ReadSessionWindow,
                SessionId: sessionId,
                FirstSequence: firstSequence,
                Limit: limit),
            cancellationToken);

    public Task<ControlResponse> ExportSessionCsvAsync(
        Guid sessionId,
        string path,
        CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(
                ControlOperations.ExportSessionCsv,
                SessionId: sessionId,
                OutputPath: path),
            cancellationToken);

    public Task<ControlResponse> ExportDiagnosticsAsync(
        string path,
        string language,
        CancellationToken cancellationToken) =>
        SendAsync(
            new ControlRequest(
                ControlOperations.ExportDiagnostics,
                OutputPath: path,
                Language: language),
            cancellationToken);

    public async ValueTask DisposeAsync()
    {
        if (_pipe is not null)
        {
            await _pipe.DisposeAsync().ConfigureAwait(false);
            _pipe = null;
        }

        _operationLock.Dispose();
    }

    private async Task<ControlResponse> SendAsync(
        ControlRequest request,
        CancellationToken cancellationToken)
    {
        if (_pipe?.IsConnected != true)
        {
            throw new InvalidOperationException("The acquisition control pipe is not connected.");
        }

        await _operationLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await ControlPipeProtocol.WriteAsync(
                _pipe,
                request,
                cancellationToken).ConfigureAwait(false);
            ControlResponse response =
                await ControlPipeProtocol.ReadAsync<ControlResponse>(
                    _pipe,
                    cancellationToken).ConfigureAwait(false);
            if (!response.Success)
            {
                throw new InvalidOperationException(response.Message);
            }

            return response;
        }
        finally
        {
            _operationLock.Release();
        }
    }
}
