using System.Globalization;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Visa;

public sealed class Fluke8508ADriver : VisaInstrumentDriverBase
{
    private static readonly IReadOnlyDictionary<int, (double Fast, double Normal)>
        DcIntegrationPlc = new Dictionary<int, (double Fast, double Normal)>
        {
            [5] = (0.165, 1),
            [6] = (1, 16),
            [7] = (64, 256),
            [8] = (256, 1_024),
        };

    public Fluke8508ADriver(
        AcquisitionSettings settings,
        IVisaBackend backend,
        TimeProvider? timeProvider = null)
        : base(InstrumentModel.Fluke8508A, settings, backend, timeProvider)
    {
    }

    public override async ValueTask<InstrumentIdentity> ConnectAsync(
        CancellationToken cancellationToken)
    {
        if (!VisaDriverUtilities.IsGpibInstrument(Resource))
        {
            throw new InstrumentDriverException(
                "The Fluke 8508A requires an IEEE-488/GPIB VISA INSTR resource.");
        }

        try
        {
            await OpenSessionAsync(cancellationToken).ConfigureAwait(false);
            RequireSession().TimeoutMilliseconds = 30_000;
            string identity = await QueryAsync("*IDN?", cancellationToken).ConfigureAwait(false);
            if (!identity.Contains("FLUKE", StringComparison.OrdinalIgnoreCase) ||
                !identity.Contains("8508A", StringComparison.OrdinalIgnoreCase))
            {
                throw new InstrumentDriverException(
                    $"{Resource} reported '{identity}', not a Fluke 8508A.");
            }

            string[] fields = identity.Split(',');
            string firmware = fields.Length > 3 ? fields[3].Trim() : string.Empty;
            Identity = new InstrumentIdentity(
                InstrumentModel.Fluke8508A,
                identity,
                Resource,
                firmware,
                string.Empty,
                50);
            return Identity;
        }
        catch
        {
            await DisconnectAsync(CancellationToken.None).ConfigureAwait(false);
            throw;
        }
    }

    public override async ValueTask ConfigureAsync(
        AcquisitionSettings settings,
        CancellationToken cancellationToken)
    {
        settings.Validate();
        string command = FunctionCommand(settings);
        RequireSession().TimeoutMilliseconds = Math.Max(
            30_000,
            checked((int)((settings.Nplc / 50 + 8) * 1_000)));
        foreach (string item in new[] { "*CLS", command, "TRG_SRCE EXT" })
        {
            await WriteAsync(item, cancellationToken).ConfigureAwait(false);
        }

        int status = (int)FirstNumber(
            await QueryAsync("*ESR?", cancellationToken).ConfigureAwait(false),
            "*ESR?");
        int errorBits = status & 0x3C;
        if (errorBits != 0)
        {
            string detail = string.Empty;
            if ((errorBits & 0x10) != 0)
            {
                detail = $"; execution error {(int)FirstNumber(
                    await QueryAsync("EXQ?", cancellationToken).ConfigureAwait(false),
                    "EXQ?")}";
            }
            else if ((errorBits & 0x08) != 0)
            {
                detail = $"; device error {(int)FirstNumber(
                    await QueryAsync("DDQ?", cancellationToken).ConfigureAwait(false),
                    "DDQ?")}";
            }

            throw new InstrumentDriverException(
                $"Fluke 8508A configuration error ESR={status}{detail}.");
        }

        Settings = settings;
    }

    public override async ValueTask<Measurement> ReadAsync(
        ChannelId channel,
        long sequence,
        TimeSpan elapsed,
        bool includeTemperature,
        CancellationToken cancellationToken)
    {
        _ = includeTemperature;
        double value = FirstNumber(
            await QueryAsync("X?", cancellationToken).ConfigureAwait(false),
            "X?");
        return new Measurement(
            channel,
            sequence,
            DateTimeOffset.UtcNow,
            elapsed,
            value,
            Settings.Function.Unit(),
            null);
    }

    private static string FunctionCommand(AcquisitionSettings settings)
    {
        string range = settings.MeasurementRange.Equals(
            "AUTO",
            StringComparison.OrdinalIgnoreCase)
            ? "AUTO"
            : settings.MeasurementRange;
        int requestedDigits = Math.Clamp(settings.Digits, 5, 8);
        int digits = settings.Function switch
        {
            MeasurementFunction.AcVoltage or MeasurementFunction.AcCurrent =>
                Math.Min(requestedDigits, 6),
            MeasurementFunction.DcCurrent => Math.Min(requestedDigits, 7),
            _ => requestedDigits,
        };
        string resolution = $"RESL{digits.ToString(CultureInfo.InvariantCulture)}";
        string fast = FastMode(digits, settings.Nplc);
        return settings.Function switch
        {
            MeasurementFunction.DcVoltage =>
                $"DCV {range},FILT_OFF,{resolution},{fast},TWO_WR",
            MeasurementFunction.AcVoltage =>
                $"ACV {range},FILT40HZ,ACCP,TFER_ON,{resolution},SPOT_OFF,TWO_WR",
            MeasurementFunction.Resistance2Wire =>
                $"OHMS {range},FILT_OFF,{resolution},{fast},TWO_WR,LOI_OFF",
            MeasurementFunction.Resistance4Wire =>
                $"OHMS {range},FILT_OFF,{resolution},{fast},FOUR_WR,LOI_OFF",
            MeasurementFunction.DcCurrent =>
                $"DCI {range},FILT_OFF,{resolution},{fast}",
            MeasurementFunction.AcCurrent =>
                $"ACI {range},FILT40HZ,ACCP,{resolution}",
            _ => throw new InstrumentDriverException(
                $"Fluke 8508A does not support {settings.Function}."),
        };
    }

    private static string FastMode(int digits, double requestedNplc)
    {
        (double fast, double normal) = DcIntegrationPlc[digits];
        return Math.Abs(requestedNplc - fast) <= Math.Abs(requestedNplc - normal)
            ? "FAST_ON"
            : "FAST_OFF";
    }
}
