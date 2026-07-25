using PrecisionLab.Domain;

namespace PrecisionLab.Contracts;

public static class ControlOperations
{
    public const string Hello = "hello";
    public const string Snapshot = "snapshot";
    public const string Start = "start";
    public const string Stop = "stop";
    public const string StopAll = "stop-all";
    public const string DiscoverResources = "discover-resources";
    public const string ListSessions = "list-sessions";
    public const string ReadSessionWindow = "read-session-window";
    public const string ExportSessionCsv = "export-session-csv";
    public const string ExportDiagnostics = "export-diagnostics";
}

public sealed record ControlRequest(
    string Operation,
    IReadOnlyList<ChannelId>? Channels = null,
    IReadOnlyDictionary<ChannelId, AcquisitionSettings>? Settings = null,
    Guid? SessionId = null,
    long FirstSequence = 0,
    int Limit = 20_000,
    string? OutputPath = null,
    string Language = "en",
    int ProtocolVersion = PipeNames.ProtocolVersion);

public sealed record ControlResponse(
    bool Success,
    string Message,
    ServiceSnapshot? Snapshot,
    IReadOnlyList<string>? Resources = null,
    IReadOnlyList<SessionSummary>? Sessions = null,
    IReadOnlyList<Measurement>? Measurements = null,
    string? OutputPath = null,
    int ProtocolVersion = PipeNames.ProtocolVersion);
