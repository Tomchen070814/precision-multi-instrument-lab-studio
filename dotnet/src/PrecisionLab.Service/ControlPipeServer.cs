using System.IO.Pipes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Acquisition;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Service;

public sealed partial class ControlPipeServer : BackgroundService
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
        LogControlPipeReady(_logger, PipeNames.Control);
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
                await ServeClientAsync(pipe, stoppingToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (IOException exception)
            {
                LogControlClientDisconnected(_logger, exception);
            }
        }
    }

    private async Task ServeClientAsync(
        NamedPipeServerStream pipe,
        CancellationToken cancellationToken)
    {
        while (pipe.IsConnected && !cancellationToken.IsCancellationRequested)
        {
            ControlRequest request;
            try
            {
                request = await ControlPipeProtocol
                    .ReadAsync<ControlRequest>(pipe, cancellationToken)
                    .ConfigureAwait(false);
            }
            catch (EndOfStreamException exception)
            {
                LogControlClientDisconnected(_logger, exception);
                return;
            }
            catch (IOException exception)
            {
                LogControlClientDisconnected(_logger, exception);
                return;
            }

            ControlResponse response;
            try
            {
                response = await HandleAsync(request, cancellationToken)
                    .ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                LogControlRequestFailed(_logger, exception);
                response = new ControlResponse(
                    false,
                    exception.Message,
                    _coordinator.Snapshot());
            }

            try
            {
                await ControlPipeProtocol.WriteAsync(
                    pipe,
                    response,
                    cancellationToken).ConfigureAwait(false);
            }
            catch (IOException exception)
            {
                LogControlClientDisconnected(_logger, exception);
                return;
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

    [LoggerMessage(
        EventId = 100,
        Level = LogLevel.Information,
        Message = "Control pipe {PipeName} is ready.")]
    private static partial void LogControlPipeReady(ILogger logger, string pipeName);

    [LoggerMessage(
        EventId = 101,
        Level = LogLevel.Debug,
        Message = "A control-pipe client disconnected.")]
    private static partial void LogControlClientDisconnected(
        ILogger logger,
        Exception exception);

    [LoggerMessage(
        EventId = 102,
        Level = LogLevel.Error,
        Message = "Control request failed.")]
    private static partial void LogControlRequestFailed(
        ILogger logger,
        Exception exception);
}
