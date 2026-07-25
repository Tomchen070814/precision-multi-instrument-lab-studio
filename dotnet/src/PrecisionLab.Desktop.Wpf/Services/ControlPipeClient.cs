using System.IO.Pipes;
using PrecisionLab.Contracts;

namespace PrecisionLab.Desktop.Wpf.Services;

public sealed class ControlPipeClient
{
    public async Task<ControlResponse> SendAsync(
        ControlRequest request,
        CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(3));
        await using var pipe = new NamedPipeClientStream(
            ".",
            PipeNames.Control,
            PipeDirection.InOut,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        await pipe.ConnectAsync(timeout.Token).ConfigureAwait(false);
        await ControlPipeProtocol.WriteAsync(pipe, request, timeout.Token).ConfigureAwait(false);
        return await ControlPipeProtocol
            .ReadAsync<ControlResponse>(pipe, timeout.Token)
            .ConfigureAwait(false);
    }
}
