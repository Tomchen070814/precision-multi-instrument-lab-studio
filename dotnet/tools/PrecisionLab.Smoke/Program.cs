using System.IO.Pipes;
using PrecisionLab.Contracts;
using PrecisionLab.Domain;

return await SmokeProgram.RunAsync(args).ConfigureAwait(false);

internal static class SmokeProgram
{
    public static async Task<int> RunAsync(string[] arguments)
    {
        string mode = arguments.FirstOrDefault() ?? "verify";
        string outputDirectory = arguments.Length > 1
            ? Path.GetFullPath(arguments[1])
            : Path.Combine(Path.GetTempPath(), "PrecisionLabSmoke");
        Directory.CreateDirectory(outputDirectory);
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(45));
            return mode.ToLowerInvariant() switch
            {
                "start" => await StartAndDetachAsync(timeout.Token).ConfigureAwait(false),
                "verify" => await VerifyCompletedAsync(
                    outputDirectory,
                    timeout.Token).ConfigureAwait(false),
                "start-crash" => await StartCrashSessionAsync(
                    timeout.Token).ConfigureAwait(false),
                "verify-recovery" => await VerifyRecoveryAsync(
                    timeout.Token).ConfigureAwait(false),
                _ => throw new ArgumentException($"Unknown smoke mode '{mode}'."),
            };
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }

    private static async Task<int> StartAndDetachAsync(
        CancellationToken cancellationToken)
    {
        await using var control = await ControlConnection.OpenAsync(
            cancellationToken).ConfigureAwait(false);
        await using var data = await DataConnection.OpenAsync(
            cancellationToken).ConfigureAwait(false);
        var settings = new Dictionary<ChannelId, AcquisitionSettings>
        {
            [ChannelId.A] = DigitalTwin(
                InstrumentModel.Keysight3458A,
                MeasurementFunction.DcVoltage,
                "SIM::SMOKE-A"),
            [ChannelId.B] = DigitalTwin(
                InstrumentModel.Fluke8508A,
                MeasurementFunction.Resistance4Wire,
                "SIM::SMOKE-B"),
            [ChannelId.C] = DigitalTwin(
                InstrumentModel.Fluke8588A,
                MeasurementFunction.DcCurrent,
                "SIM::SMOKE-C"),
        };
        await control.SendAsync(
            new ControlRequest(
                ControlOperations.Start,
                Enum.GetValues<ChannelId>(),
                settings),
            cancellationToken).ConfigureAwait(false);

        var seen = new HashSet<ChannelId>();
        while (seen.Count < 3)
        {
            Measurement measurement = await data.ReadAsync(
                cancellationToken).ConfigureAwait(false);
            seen.Add(measurement.Channel);
        }

        ControlResponse snapshot = await control.SendAsync(
            new ControlRequest(ControlOperations.Snapshot),
            cancellationToken).ConfigureAwait(false);
        Ensure(
            snapshot.Snapshot?.Channels.All(item => item.CommittedSamples > 0) == true,
            "No committed samples were visible before the client detached.");
        Console.WriteLine("Detached after receiving durable data from A/B/C.");
        return 0;
    }

    private static async Task<int> VerifyCompletedAsync(
        string outputDirectory,
        CancellationToken cancellationToken)
    {
        await using var control = await ControlConnection.OpenAsync(
            cancellationToken).ConfigureAwait(false);
        ServiceSnapshot snapshot;
        do
        {
            ControlResponse response = await control.SendAsync(
                new ControlRequest(ControlOperations.Snapshot),
                cancellationToken).ConfigureAwait(false);
            snapshot = response.Snapshot ??
                throw new InvalidDataException("Service snapshot was missing.");
            if (snapshot.Channels.Any(item => item.State is not ChannelState.Stopped))
            {
                await Task.Delay(50, cancellationToken).ConfigureAwait(false);
            }
        }
        while (snapshot.Channels.Any(item => item.State is not ChannelState.Stopped));

        Ensure(
            snapshot.Channels.All(item => item.CommittedSamples == 60),
            "One or more channels did not commit exactly 60 samples.");
        ControlResponse sessionsResponse = await control.SendAsync(
            new ControlRequest(ControlOperations.ListSessions, Limit: 20),
            cancellationToken).ConfigureAwait(false);
        SessionSummary[] completed = (sessionsResponse.Sessions ?? [])
            .Where(item => item.Status == "Completed" && item.SampleCount == 60)
            .Take(3)
            .ToArray();
        Ensure(completed.Length == 3, "Three completed digital-twin sessions were not found.");

        foreach (SessionSummary session in completed)
        {
            ControlResponse readings = await control.SendAsync(
                new ControlRequest(
                    ControlOperations.ReadSessionWindow,
                    SessionId: session.Id,
                    Limit: 100),
                cancellationToken).ConfigureAwait(false);
            Ensure(
                readings.Measurements?.Count == 60,
                $"Session {session.Id:D} did not return 60 measurements.");
        }

        string csv = Path.Combine(outputDirectory, "smoke-session.csv");
        await control.SendAsync(
            new ControlRequest(
                ControlOperations.ExportSessionCsv,
                SessionId: completed[0].Id,
                OutputPath: csv),
            cancellationToken).ConfigureAwait(false);
        string diagnostic = Path.Combine(outputDirectory, "smoke-diagnostic.zip");
        await control.SendAsync(
            new ControlRequest(
                ControlOperations.ExportDiagnostics,
                OutputPath: diagnostic,
                Language: "zh-CN"),
            cancellationToken).ConfigureAwait(false);
        Ensure(File.Exists(csv) && new FileInfo(csv).Length > 100, "CSV export failed.");
        Ensure(
            File.Exists(diagnostic) && new FileInfo(diagnostic).Length > 100,
            "Diagnostic ZIP export failed.");
        Console.WriteLine("Verified client-detach continuation, 180 commits, requery and exports.");
        return 0;
    }

    private static async Task<int> StartCrashSessionAsync(
        CancellationToken cancellationToken)
    {
        await using var control = await ControlConnection.OpenAsync(
            cancellationToken).ConfigureAwait(false);
        await using var data = await DataConnection.OpenAsync(
            cancellationToken).ConfigureAwait(false);
        AcquisitionSettings settings = DigitalTwin(
            InstrumentModel.Keysight34470A,
            MeasurementFunction.DcVoltage,
            "SIM::CRASH") with
        {
            MaxSamples = null,
        };
        await control.SendAsync(
            new ControlRequest(
                ControlOperations.Start,
                [ChannelId.A],
                new Dictionary<ChannelId, AcquisitionSettings>
                {
                    [ChannelId.A] = settings,
                }),
            cancellationToken).ConfigureAwait(false);
        for (int index = 0; index < 10; index++)
        {
            _ = await data.ReadAsync(cancellationToken).ConfigureAwait(false);
        }

        Console.WriteLine("Continuous session has durable commits and is ready for forced kill.");
        return 0;
    }

    private static async Task<int> VerifyRecoveryAsync(
        CancellationToken cancellationToken)
    {
        await using var control = await ControlConnection.OpenAsync(
            cancellationToken).ConfigureAwait(false);
        ControlResponse response = await control.SendAsync(
            new ControlRequest(ControlOperations.ListSessions, Limit: 100),
            cancellationToken).ConfigureAwait(false);
        SessionSummary? interrupted = (response.Sessions ?? [])
            .FirstOrDefault(item =>
                item.Status == "Interrupted" &&
                item.Resource == "SIM::CRASH" &&
                item.SampleCount >= 10);
        if (interrupted is null)
        {
            throw new InvalidOperationException(
                "Interrupted crash session was not recovered.");
        }

        Console.WriteLine(
            $"Recovered interrupted session {interrupted.Id:D} with " +
            $"{interrupted.SampleCount} committed samples.");
        return 0;
    }

    private static AcquisitionSettings DigitalTwin(
        InstrumentModel model,
        MeasurementFunction function,
        string resource) =>
        new()
        {
            InstrumentModel = model,
            Function = function,
            Resource = resource,
            Nplc = 1,
            Digits = model == InstrumentModel.Fluke8508A ? 7 : 8,
            SampleInterval = TimeSpan.FromMilliseconds(5),
            MaxSamples = 60,
        };

    private static void Ensure(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private sealed class ControlConnection : IAsyncDisposable
    {
        private readonly NamedPipeClientStream _pipe;

        private ControlConnection(NamedPipeClientStream pipe)
        {
            _pipe = pipe;
        }

        public static async Task<ControlConnection> OpenAsync(
            CancellationToken cancellationToken)
        {
            var pipe = new NamedPipeClientStream(
                ".",
                PipeNames.Control,
                PipeDirection.InOut,
                PipeOptions.Asynchronous);
            await pipe.ConnectAsync(5_000, cancellationToken).ConfigureAwait(false);
            var connection = new ControlConnection(pipe);
            await connection.SendAsync(
                new ControlRequest(ControlOperations.Hello),
                cancellationToken).ConfigureAwait(false);
            return connection;
        }

        public async Task<ControlResponse> SendAsync(
            ControlRequest request,
            CancellationToken cancellationToken)
        {
            await ControlPipeProtocol.WriteAsync(
                _pipe,
                request,
                cancellationToken).ConfigureAwait(false);
            ControlResponse response =
                await ControlPipeProtocol.ReadAsync<ControlResponse>(
                    _pipe,
                    cancellationToken).ConfigureAwait(false);
            if (!response.Success)
            {
                throw new InvalidOperationException(response.Message);
            }

            return response;
        }

        public ValueTask DisposeAsync() => _pipe.DisposeAsync();
    }

    private sealed class DataConnection : IAsyncDisposable
    {
        private readonly NamedPipeClientStream _pipe;

        private DataConnection(NamedPipeClientStream pipe)
        {
            _pipe = pipe;
        }

        public static async Task<DataConnection> OpenAsync(
            CancellationToken cancellationToken)
        {
            var pipe = new NamedPipeClientStream(
                ".",
                PipeNames.Data,
                PipeDirection.In,
                PipeOptions.Asynchronous);
            await pipe.ConnectAsync(5_000, cancellationToken).ConfigureAwait(false);
            return new DataConnection(pipe);
        }

        public ValueTask<Measurement> ReadAsync(CancellationToken cancellationToken) =>
            DataFrameCodec.ReadMeasurementAsync(_pipe, cancellationToken);

        public ValueTask DisposeAsync() => _pipe.DisposeAsync();
    }
}
