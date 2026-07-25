using System.IO.Pipes;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PrecisionLab.Acquisition;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;
using PrecisionLab.Export;
using PrecisionLab.Storage;

namespace PrecisionLab.Service;

public sealed partial class ControlPipeServer : BackgroundService
{
    private readonly AcquisitionCoordinator _coordinator;
    private readonly IVisaBackend _visaBackend;
    private readonly ISessionStore _store;
    private readonly ILogger<ControlPipeServer> _logger;

    public ControlPipeServer(
        AcquisitionCoordinator coordinator,
        IVisaBackend visaBackend,
        ISessionStore store,
        ILogger<ControlPipeServer> logger)
    {
        _coordinator = coordinator;
        _visaBackend = visaBackend;
        _store = store;
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
            case ControlOperations.DiscoverResources:
                return new ControlResponse(
                    true,
                    "ok",
                    _coordinator.Snapshot(),
                    Resources: await _visaBackend.DiscoverAsync(
                        cancellationToken).ConfigureAwait(false));
            case ControlOperations.ListSessions:
            {
                IReadOnlyList<SessionInfo> sessions = await _store.ListSessionsAsync(
                    Math.Clamp(request.Limit, 1, 10_000),
                    cancellationToken).ConfigureAwait(false);
                return new ControlResponse(
                    true,
                    "ok",
                    _coordinator.Snapshot(),
                    Sessions: sessions.Select(ToSummary).ToArray());
            }
            case ControlOperations.ReadSessionWindow:
            {
                Guid sessionId = request.SessionId ??
                    throw new ArgumentException("SessionId is required.");
                IReadOnlyList<Measurement> measurements =
                    await _store.ReadMeasurementsAsync(
                        sessionId,
                        request.FirstSequence,
                        Math.Clamp(request.Limit, 1, 50_000),
                        cancellationToken).ConfigureAwait(false);
                return new ControlResponse(
                    true,
                    "ok",
                    _coordinator.Snapshot(),
                    Measurements: measurements);
            }
            case ControlOperations.ExportSessionCsv:
            {
                Guid sessionId = request.SessionId ??
                    throw new ArgumentException("SessionId is required.");
                string outputPath = request.OutputPath ??
                    throw new ArgumentException("OutputPath is required.");
                await CsvDataExchange.ExportSessionAsync(
                    outputPath,
                    sessionId,
                    _store,
                    cancellationToken).ConfigureAwait(false);
                return new ControlResponse(
                    true,
                    "ok",
                    _coordinator.Snapshot(),
                    OutputPath: Path.GetFullPath(outputPath));
            }
            case ControlOperations.ExportDiagnostics:
            {
                string outputPath = request.OutputPath ??
                    throw new ArgumentException("OutputPath is required.");
                string created = await DiagnosticReportWriter.CreateAsync(
                    outputPath,
                    _coordinator.Snapshot(),
                    _store.DatabasePath,
                    request.Language,
                    cancellationToken: cancellationToken).ConfigureAwait(false);
                return new ControlResponse(
                    true,
                    "ok",
                    _coordinator.Snapshot(),
                    OutputPath: created);
            }
            default:
                return new ControlResponse(
                    false,
                    $"Unknown operation '{request.Operation}'.",
                    _coordinator.Snapshot());
        }

        return new ControlResponse(true, "ok", _coordinator.Snapshot());
    }

    private static SessionSummary ToSummary(SessionInfo session) =>
        new(
            session.Id,
            session.Channel,
            session.InstrumentModel,
            session.Function,
            session.Resource,
            session.StartedUtc,
            session.EndedUtc,
            session.Status.ToString(),
            session.Unit,
            session.SampleCount,
            session.CommittedSequence,
            session.Error);

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
