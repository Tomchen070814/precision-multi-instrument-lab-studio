using System.IO.Pipes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Acquisition;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Service;

public sealed class DataPipeServer : BackgroundService
{
    private readonly MeasurementHub _hub;
    private readonly ILogger<DataPipeServer> _logger;

    public DataPipeServer(MeasurementHub hub, ILogger<DataPipeServer> logger)
    {
        _hub = hub;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Data pipe {PipeName} is ready.", PipeNames.Data);
        while (!stoppingToken.IsCancellationRequested)
        {
            NamedPipeServerStream? pipe = new(
                PipeNames.Data,
                PipeDirection.Out,
                NamedPipeServerStream.MaxAllowedServerInstances,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            try
            {
                await pipe.WaitForConnectionAsync(stoppingToken).ConfigureAwait(false);
                NamedPipeServerStream connectedPipe = pipe;
                pipe = null;
                _ = StreamMeasurementsAsync(connectedPipe, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            finally
            {
                if (pipe is not null)
                {
                    await pipe.DisposeAsync().ConfigureAwait(false);
                }
            }
        }
    }

    private async Task StreamMeasurementsAsync(
        NamedPipeServerStream pipe,
        CancellationToken cancellationToken)
    {
        await using (pipe.ConfigureAwait(false))
        using (MeasurementSubscription subscription = _hub.Subscribe())
        {
            try
            {
                await foreach (Measurement measurement in subscription.Reader.ReadAllAsync(
                                   cancellationToken))
                {
                    await DataFrameCodec.WriteMeasurementAsync(
                        pipe,
                        measurement,
                        cancellationToken).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // Normal service shutdown.
            }
            catch (IOException exception)
            {
                _logger.LogDebug(exception, "A data-pipe client disconnected.");
            }
        }
    }
}
