using System.IO;
using System.IO.Pipes;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.Services;

public sealed class DataPipeClient : IAsyncDisposable
{
    private readonly CancellationTokenSource _lifetime = new();
    private NamedPipeClientStream? _pipe;
    private Task? _readerTask;

    public event Action<Measurement>? MeasurementReceived;

    public bool IsConnected => _pipe?.IsConnected == true;

    public async Task ConnectAsync(CancellationToken cancellationToken)
    {
        if (IsConnected)
        {
            return;
        }

        if (_pipe is not null)
        {
            await _pipe.DisposeAsync().ConfigureAwait(false);
        }

        _pipe = new NamedPipeClientStream(
            ".",
            PipeNames.Data,
            PipeDirection.In,
            PipeOptions.Asynchronous);
        await _pipe.ConnectAsync(3_000, cancellationToken).ConfigureAwait(false);
        _readerTask = ReadLoopAsync(_lifetime.Token);
    }

    public async ValueTask DisposeAsync()
    {
        _lifetime.Cancel();
        if (_pipe is not null)
        {
            await _pipe.DisposeAsync().ConfigureAwait(false);
            _pipe = null;
        }

        if (_readerTask is not null)
        {
            try
            {
                await _readerTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        _lifetime.Dispose();
    }

    private async Task ReadLoopAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (_pipe?.IsConnected == true && !cancellationToken.IsCancellationRequested)
            {
                Measurement measurement = await DataFrameCodec.ReadMeasurementAsync(
                    _pipe,
                    cancellationToken).ConfigureAwait(false);
                MeasurementReceived?.Invoke(measurement);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (EndOfStreamException)
        {
        }
        catch (IOException)
        {
        }
    }
}
