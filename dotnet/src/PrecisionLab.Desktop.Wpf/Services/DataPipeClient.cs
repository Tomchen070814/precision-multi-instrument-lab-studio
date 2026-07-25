using System.IO.Pipes;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.Services;

public sealed class DataPipeClient : IAsyncDisposable
{
    private readonly CancellationTokenSource _lifetime = new();
    private Task? _readerTask;

    public event Action<Measurement>? MeasurementReceived;

    public void Start()
    {
        _readerTask ??= Task.Run(() => ReadLoopAsync(_lifetime.Token), CancellationToken.None);
    }

    public async ValueTask DisposeAsync()
    {
        _lifetime.Cancel();
        if (_readerTask is not null)
        {
            try
            {
                await _readerTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Normal client shutdown.
            }
        }

        _lifetime.Dispose();
    }

    private async Task ReadLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await using var pipe = new NamedPipeClientStream(
                    ".",
                    PipeNames.Data,
                    PipeDirection.In,
                    PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await pipe.ConnectAsync(cancellationToken).ConfigureAwait(false);
                while (pipe.IsConnected && !cancellationToken.IsCancellationRequested)
                {
                    Measurement measurement = await DataFrameCodec
                        .ReadMeasurementAsync(pipe, cancellationToken)
                        .ConfigureAwait(false);
                    MeasurementReceived?.Invoke(measurement);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
            catch (IOException)
            {
                await Task.Delay(TimeSpan.FromSeconds(1), cancellationToken).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                await Task.Delay(TimeSpan.FromSeconds(1), cancellationToken).ConfigureAwait(false);
            }
        }
    }
}
