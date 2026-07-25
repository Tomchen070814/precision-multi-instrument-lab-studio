using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;
using PrecisionLab.Drivers.Visa;

namespace PrecisionLab.Core.Tests;

public sealed class VisaDriverTranscriptTests
{
    [Fact]
    public async Task AllFourteenModelsConnectConfigureAndReadThroughTheirProfiles()
    {
        foreach (InstrumentDescriptor descriptor in InstrumentCatalog.All)
        {
            string resource = descriptor.RequiresGpib
                ? $"GPIB0::{10 + (int)descriptor.Model}::INSTR"
                : $"TCPIP0::192.0.2.{10 + (int)descriptor.Model}::inst0::INSTR";
            var backend = new TranscriptBackend(descriptor);
            var settings = new AcquisitionSettings
            {
                InstrumentModel = descriptor.Model,
                Function = descriptor.SupportedFunctions[0],
                Resource = resource,
                Nplc = Math.Clamp(10, descriptor.MinimumNplc, descriptor.MaximumNplc),
                Digits = descriptor.Model == InstrumentModel.Fluke8508A ? 7 : 8,
                IncludeTemperature = true,
            };
            await using IInstrumentDriver driver =
                new VisaInstrumentDriverFactory(backend).Create(ChannelId.A, settings);

            InstrumentIdentity identity =
                await driver.ConnectAsync(CancellationToken.None);
            await driver.ConfigureAsync(settings, CancellationToken.None);
            Measurement reading = await driver.ReadAsync(
                ChannelId.A,
                0,
                TimeSpan.Zero,
                includeTemperature: true,
                CancellationToken.None);

            Assert.Contains(
                descriptor.IdentityTokens[0],
                identity.ReportedModel,
                StringComparison.OrdinalIgnoreCase);
            Assert.Equal(1.2345, reading.Value, 10);
            Assert.Contains(
                backend.Session.Commands,
                command => command.Contains(
                    descriptor.Protocol == InstrumentProtocol.HpIb3458A
                        ? "ID?"
                        : "*IDN?",
                    StringComparison.Ordinal));
        }
    }

    [Fact]
    public async Task Legacy3458AReceivesNoGenericScpiInitialization()
    {
        InstrumentDescriptor descriptor =
            InstrumentCatalog.Get(InstrumentModel.Keysight3458A);
        var backend = new TranscriptBackend(descriptor);
        var settings = new AcquisitionSettings
        {
            InstrumentModel = InstrumentModel.Keysight3458A,
            Resource = "GPIB0::22::INSTR",
        };
        await using var driver = new Keysight3458ADriver(settings, backend);

        await driver.ConnectAsync(CancellationToken.None);
        await driver.ConfigureAsync(settings, CancellationToken.None);

        Assert.DoesNotContain(
            backend.Session.Commands,
            command => command.Contains("*IDN?", StringComparison.Ordinal) ||
                command.Contains("CONF:", StringComparison.Ordinal));
        Assert.Contains(
            backend.Session.Commands,
            command => command.Contains("PRESET NORM", StringComparison.Ordinal));
    }

    [Fact]
    public async Task WrongIdentityIsRejectedBeforeConfiguration()
    {
        InstrumentDescriptor descriptor =
            InstrumentCatalog.Get(InstrumentModel.Keysight34470A);
        var backend = new TranscriptBackend(descriptor, "ACME,NOT-A-DMM,0,1");
        var settings = new AcquisitionSettings
        {
            InstrumentModel = descriptor.Model,
            Resource = "TCPIP0::192.0.2.10::inst0::INSTR",
        };
        await using var driver = new ScpiDmmDriver(settings, backend);

        await Assert.ThrowsAsync<InstrumentDriverException>(
            () => driver.ConnectAsync(CancellationToken.None).AsTask());
        Assert.DoesNotContain(
            backend.Session.Commands,
            command => command.StartsWith("CONF:", StringComparison.Ordinal));
    }

    private sealed class TranscriptBackend : IVisaBackend
    {
        private readonly InstrumentDescriptor _descriptor;
        private readonly string? _identityOverride;

        public TranscriptBackend(
            InstrumentDescriptor descriptor,
            string? identityOverride = null)
        {
            _descriptor = descriptor;
            _identityOverride = identityOverride;
            Session = new TranscriptSession(Respond);
        }

        public TranscriptSession Session { get; }

        public ValueTask<IReadOnlyList<string>> DiscoverAsync(
            CancellationToken cancellationToken) =>
            ValueTask.FromResult<IReadOnlyList<string>>(["GPIB0::22::INSTR"]);

        public ValueTask<IVisaMessageSession> OpenAsync(
            string resource,
            string backend,
            CancellationToken cancellationToken)
        {
            _ = resource;
            _ = backend;
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult<IVisaMessageSession>(Session);
        }

        private string Respond(string command)
        {
            if (command == "ID?")
            {
                return _identityOverride ?? "HEWLETT-PACKARD,3458A";
            }

            if (command == "*IDN?")
            {
                return _identityOverride ??
                    $"{_descriptor.Manufacturer},{_descriptor.ShortName},0,1.0";
            }

            return command switch
            {
                "REV?" => "9.2",
                "OPT?" => "1",
                "LINE?" or "SYST:LFREQ?" => "50",
                "ERR?" or "*ESR?" => "0",
                "SYST:ERR?" or "SYST:ERR:NEXT?" => "+0,\"No error\"",
                "TEMP?" or "SYST:TEMP?" => "23.5",
                "READ? TEMP" => "1.2345,23.5",
                "READ?" or "X?" or "TRIG SGL" => "1.2345",
                _ => "0",
            };
        }
    }

    private sealed class TranscriptSession : IVisaMessageSession
    {
        private readonly Func<string, string> _respond;
        private string _lastCommand = string.Empty;

        public TranscriptSession(Func<string, string> respond)
        {
            _respond = respond;
        }

        public List<string> Commands { get; } = [];

        public string Resource => "TRANSCRIPT";

        public int TimeoutMilliseconds { get; set; }

        public ValueTask ClearAsync(CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Commands.Add("<CLEAR>");
            return ValueTask.CompletedTask;
        }

        public ValueTask WriteAsync(
            string command,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Commands.Add(command);
            _lastCommand = command;
            return ValueTask.CompletedTask;
        }

        public ValueTask<string> ReadAsync(CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(_respond(_lastCommand));
        }

        public ValueTask AbortAsync(CancellationToken cancellationToken) =>
            ValueTask.CompletedTask;

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
