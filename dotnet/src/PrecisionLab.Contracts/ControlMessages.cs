using PrecisionLab.Domain;

namespace PrecisionLab.Contracts;

public static class ControlOperations
{
    public const string Hello = "hello";
    public const string Snapshot = "snapshot";
    public const string Start = "start";
    public const string Stop = "stop";
    public const string StopAll = "stop-all";
}

public sealed record ControlRequest(
    string Operation,
    IReadOnlyList<ChannelId>? Channels = null,
    IReadOnlyDictionary<ChannelId, AcquisitionSettings>? Settings = null,
    int ProtocolVersion = PipeNames.ProtocolVersion);

public sealed record ControlResponse(
    bool Success,
    string Message,
    ServiceSnapshot? Snapshot,
    int ProtocolVersion = PipeNames.ProtocolVersion);
