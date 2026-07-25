using System.IO.Pipes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Acquisition;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Service;

public sealed class ControlPipeServer : BackgroundService
{
    private readonly AcquisitionCoordinator _coordinator;
    private readonly ILogger<ControlPipeServer> _logger;

    public ControlPipeServer(
        AcquisitionCoordinator coordinator,
        ILogger<ControlPipeServer> logger)
    {
        _coordinator = coordinator;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Control pipe {PipeName} is ready.", PipeNames.Control);
        while (!stoppingToken.IsCancellationRequested)
        {
            await using var pipe = new NamedPipeServerStream(
                PipeNames.Control,
                PipeDirection.InOut,
                NamedPipeServerStream.MaxAllowedServerInstances,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);

            try
            {
                await pipe.WaitForConnectionAsync(stoppingToken).ConfigureAwait(false);
                ControlRequest request = await ControlPipeProtocol
                    .ReadAsync<ControlRequest>(pipe, stoppingToken)
                    .ConfigureAwait(false);
                ControlResponse response = await HandleAsync(request, stoppingToken)
                    .ConfigureAwait(false);
                await ControlPipeProtocol.WriteAsync(pipe, response, stoppingToken)
                    .ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (IOException exception)
            {
                _logger.LogDebug(exception, "A control-pipe client disconnected.");
            }
            catch (Exception exception)
            {
                _logger.LogError(exception, "Control request failed.");
                if (pipe.IsConnected)
                {
                    var response = new ControlResponse(
                        false,
                        exception.Message,
                        _coordinator.Snapshot());
                    try
                    {
                        await ControlPipeProtocol.WriteAsync(
                            pipe,
                            response,
                            stoppingToken).ConfigureAwait(false);
                    }
                    catch (IOException)
                    {
                        // The client has already disconnected.
                    }
                }
            }
        }
    }

    private async Task<ControlResponse> HandleAsync(
        ControlRequest request,
        CancellationToken cancellationToken)
    {
        if (request.ProtocolVersion != PipeNames.ProtocolVersion)
        {
            return new ControlResponse(
                false,
                $"Protocol mismatch: UI={request.ProtocolVersion}, service={PipeNames.ProtocolVersion}.",
                _coordinator.Snapshot());
        }

        switch (request.Operation)
        {
            case ControlOperations.Hello:
            case ControlOperations.Snapshot:
                break;
            case ControlOperations.Start:
                await _coordinator.StartChannelsAsync(
                    request.Channels ?? [ChannelId.A, ChannelId.B],
                    request.Settings,
                    cancellationToken).ConfigureAwait(false);
                break;
            case ControlOperations.Stop:
                await _coordinator.StopChannelsAsync(
                    request.Channels ?? [],
                    cancellationToken).ConfigureAwait(false);
                break;
            case ControlOperations.StopAll:
                await _coordinator.StopChannelsAsync(
                    Enum.GetValues<ChannelId>(),
                    cancellationToken).ConfigureAwait(false);
                break;
            default:
                return new ControlResponse(
                    false,
                    $"Unknown operation '{request.Operation}'.",
                    _coordinator.Snapshot());
        }

        return new ControlResponse(true, "ok", _coordinator.Snapshot());
    }
}
