using System.IO.Pipes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Acquisition;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Service;

public sealed class ControlPipeWorker : BackgroundService
{
    private readonly AcquisitionCoordinator _coordinator;
    private readonly ILogger<ControlPipeWorker> _logger;

    public ControlPipeWorker(
        AcquisitionCoordinator coordinator,
        ILogger<ControlPipeWorker> logger)
    {
        _coordinator = coordinator;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await using var pipe = new NamedPipeServerStream(
                PipeNames.Control,
                PipeDirection.InOut,
                1,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            try
            {
                await pipe.WaitForConnectionAsync(stoppingToken).ConfigureAwait(false);
                await ServeClientAsync(pipe, stoppingToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (EndOfStreamException)
            {
                _logger.LogInformation("Control client disconnected.");
            }
            catch (IOException exception)
            {
                _logger.LogInformation(exception, "Control pipe connection ended.");
            }
            catch (Exception exception)
            {
                _logger.LogError(exception, "Control pipe failed.");
            }
        }
    }

    private async Task ServeClientAsync(
        Stream pipe,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            ControlRequest request = await ControlPipeProtocol.ReadAsync<ControlRequest>(
                pipe,
                cancellationToken).ConfigureAwait(false);
            ControlResponse response = await ExecuteRequestAsync(
                request,
                cancellationToken).ConfigureAwait(false);
            await ControlPipeProtocol.WriteAsync(
                pipe,
                response,
                cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<ControlResponse> ExecuteRequestAsync(
        ControlRequest request,
        CancellationToken cancellationToken)
    {
        if (request.ProtocolVersion != PipeNames.ProtocolVersion)
        {
            return Failure(
                $"Protocol {request.ProtocolVersion} is incompatible with " +
                $"service protocol {PipeNames.ProtocolVersion}.");
        }

        try
        {
            ChannelId[] channels = request.Channels?.Distinct().ToArray()
                ?? Enum.GetValues<ChannelId>();
            switch (request.Operation)
            {
                case ControlOperations.Hello:
                case ControlOperations.Snapshot:
                    break;

                case ControlOperations.Start:
                    await _coordinator.StartChannelsAsync(
                        channels,
                        request.Settings,
                        cancellationToken).ConfigureAwait(false);
                    break;

                case ControlOperations.Stop:
                    await _coordinator.StopChannelsAsync(
                        channels,
                        cancellationToken).ConfigureAwait(false);
                    break;

                case ControlOperations.StopAll:
                    await _coordinator.StopChannelsAsync(
                        Enum.GetValues<ChannelId>(),
                        cancellationToken).ConfigureAwait(false);
                    break;

                default:
                    return Failure($"Unknown control operation '{request.Operation}'.");
            }

            return new ControlResponse(
                true,
                $"{request.Operation} completed.",
                _coordinator.Snapshot());
        }
        catch (Exception exception)
        {
            _logger.LogError(
                exception,
                "Control operation {Operation} failed.",
                request.Operation);
            return Failure(exception.Message);
        }
    }

    private ControlResponse Failure(string message) =>
        new(false, message, _coordinator.Snapshot());
}
