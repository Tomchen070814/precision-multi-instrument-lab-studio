using System.IO.Pipes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Acquisition;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Service;

public sealed class DataPipeWorker : BackgroundService
{
    private readonly MeasurementHub _hub;
    private readonly ILogger<DataPipeWorker> _logger;

    public DataPipeWorker(
        MeasurementHub hub,
        ILogger<DataPipeWorker> logger)
    {
        _hub = hub;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await using var pipe = new NamedPipeServerStream(
                PipeNames.Data,
                PipeDirection.Out,
                1,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            using MeasurementSubscription subscription = _hub.Subscribe();

            try
            {
                await pipe.WaitForConnectionAsync(stoppingToken).ConfigureAwait(false);
                await foreach (Measurement measurement in subscription.Reader.ReadAllAsync(
                    stoppingToken))
                {
                    await DataFrameCodec.WriteMeasurementAsync(
                        pipe,
                        measurement,
                        stoppingToken).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (IOException exception)
            {
                _logger.LogInformation(
                    exception,
                    "Display client disconnected; acquisition and persistence continue.");
            }
            catch (Exception exception)
            {
                _logger.LogError(exception, "Data pipe failed.");
            }
        }
    }
}
