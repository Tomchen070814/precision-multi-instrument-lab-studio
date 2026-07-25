using System.Globalization;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Visa;

internal enum ScpiSelectionStyle : byte
{
    Configure,
    SenseQuoted,
    SenseUnquoted,
}

internal sealed record ScpiDmmProfile(
    InstrumentModel Model,
    ScpiSelectionStyle SelectionStyle = ScpiSelectionStyle.Configure,
    bool AutoInConfigure = false,
    string? RangeTemplate = "SENS:{path}:RANG {range}",
    string? AutoRangeTemplate = "SENS:{path}:RANG:AUTO ON",
    string? NplcTemplate = "SENS:{path}:NPLC {nplc}",
    string? AutozeroTemplate = "SENS:{path}:ZERO:AUTO {autozero}",
    string? LineFrequencyQuery = null,
    string? ErrorQuery = "SYST:ERR?",
    string ReadQuery = "READ?",
    string? TemperatureReadQuery = null,
    string? TemperatureQuery = null,
    IReadOnlyList<string>? PrepareCommands = null,
    IReadOnlyList<string>? TriggerCommands = null)
{
    public IReadOnlyList<string> EffectivePrepareCommands =>
        PrepareCommands ?? ["*CLS", "ABOR"];

    public IReadOnlyList<string> EffectiveTriggerCommands =>
        TriggerCommands ?? ["TRIG:SOUR IMM", "SAMP:COUN 1"];
}

public sealed class ScpiDmmDriver : VisaInstrumentDriverBase
{
    private static readonly Dictionary<MeasurementFunction, string> FunctionPaths =
        new Dictionary<MeasurementFunction, string>
        {
            [MeasurementFunction.DcVoltage] = "VOLT:DC",
            [MeasurementFunction.AcVoltage] = "VOLT:AC",
            [MeasurementFunction.Resistance2Wire] = "RES",
            [MeasurementFunction.Resistance4Wire] = "FRES",
            [MeasurementFunction.DcCurrent] = "CURR:DC",
            [MeasurementFunction.AcCurrent] = "CURR:AC",
            [MeasurementFunction.Frequency] = "FREQ",
            [MeasurementFunction.Period] = "PER",
        };

    private static readonly HashSet<MeasurementFunction> NplcFunctions =
        new HashSet<MeasurementFunction>
        {
            MeasurementFunction.DcVoltage,
            MeasurementFunction.Resistance2Wire,
            MeasurementFunction.Resistance4Wire,
            MeasurementFunction.DcCurrent,
        };

    private static readonly Dictionary<InstrumentModel, ScpiDmmProfile> Profiles =
        CreateProfiles();

    private readonly ScpiDmmProfile _profile;

    public ScpiDmmDriver(
        AcquisitionSettings settings,
        IVisaBackend backend,
        TimeProvider? timeProvider = null)
        : base(settings.InstrumentModel, settings, backend, timeProvider)
    {
        if (!Profiles.TryGetValue(settings.InstrumentModel, out ScpiDmmProfile? profile))
        {
            throw new ArgumentException(
                $"{settings.InstrumentModel} has no SCPI profile.",
                nameof(settings));
        }

        _profile = profile;
    }

    public override async ValueTask<InstrumentIdentity> ConnectAsync(
        CancellationToken cancellationToken)
    {
        if (!VisaDriverUtilities.IsVisaInstrument(Resource))
        {
            throw new InstrumentDriverException(
                $"'{Resource}' is not a supported VISA INSTR or SOCKET resource.");
        }

        try
        {
            await OpenSessionAsync(cancellationToken).ConfigureAwait(false);
            RequireSession().TimeoutMilliseconds = 15_000;
            string identity = await QueryAsync("*IDN?", cancellationToken).ConfigureAwait(false);
            InstrumentDescriptor descriptor = InstrumentCatalog.Get(InstrumentModel);
            if (!descriptor.IdentityTokens.Any(
                    token => identity.Contains(token, StringComparison.OrdinalIgnoreCase)))
            {
                throw new InstrumentDriverException(
                    $"{Resource} reported '{identity}', not {descriptor.ShortName}.");
            }

            string[] fields = identity.Split(',');
            string firmware = fields.Length > 3 ? fields[3].Trim() : string.Empty;
            double lineFrequency = 50;
            if (_profile.LineFrequencyQuery is string lineQuery)
            {
                try
                {
                    lineFrequency = FirstNumber(
                        await QueryAsync(lineQuery, cancellationToken).ConfigureAwait(false),
                        lineQuery);
                }
                catch (InstrumentDriverException)
                {
                    lineFrequency = 50;
                }
            }

            Identity = new InstrumentIdentity(
                InstrumentModel,
                identity,
                Resource,
                firmware,
                string.Empty,
                lineFrequency);
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
        InstrumentDescriptor descriptor = InstrumentCatalog.Get(InstrumentModel);
        if (!descriptor.Supports(settings.Function))
        {
            throw new InstrumentDriverException(
                $"{descriptor.ShortName} does not support {settings.Function}.");
        }

        if (!FunctionPaths.TryGetValue(settings.Function, out string? path))
        {
            throw new InstrumentDriverException(
                $"SCPI function mapping for {settings.Function} is not implemented.");
        }

        var commands = new List<string>(_profile.EffectivePrepareCommands);
        commands.AddRange(SelectionCommands(settings, path));
        commands.AddRange(_profile.EffectiveTriggerCommands);
        if (NplcFunctions.Contains(settings.Function))
        {
            if (_profile.NplcTemplate is string nplcTemplate)
            {
                commands.Add(Expand(nplcTemplate, path, settings));
            }

            if (descriptor.SupportsAutozero &&
                _profile.AutozeroTemplate is string autozeroTemplate)
            {
                commands.Add(Expand(autozeroTemplate, path, settings));
            }
        }

        double lineFrequency = Identity?.LineFrequencyHz ?? 50;
        RequireSession().TimeoutMilliseconds = Math.Max(
            15_000,
            checked((int)((settings.Nplc / Math.Max(lineFrequency, 1) + 8) * 1_000)));
        foreach (string command in commands)
        {
            await WriteAsync(command, cancellationToken).ConfigureAwait(false);
        }

        if (_profile.ErrorQuery is string errorQuery)
        {
            string error = await QueryAsync(errorQuery, cancellationToken).ConfigureAwait(false);
            if (!error.TrimStart().StartsWith("+0", StringComparison.Ordinal) &&
                !error.TrimStart().StartsWith('0'))
            {
                throw new InstrumentDriverException(
                    $"{descriptor.ShortName} configuration error: {error}");
            }
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
        string query = includeTemperature && _profile.TemperatureReadQuery is not null
            ? _profile.TemperatureReadQuery
            : _profile.ReadQuery;
        double[] values = VisaDriverUtilities.ParseNumbers(
            await QueryAsync(query, cancellationToken).ConfigureAwait(false));
        if (values.Length == 0)
        {
            throw new InstrumentDriverException(
                $"{InstrumentCatalog.Get(InstrumentModel).ShortName} returned no reading.");
        }

        double? temperature =
            includeTemperature &&
            _profile.TemperatureReadQuery is not null &&
            values.Length > 1
                ? values[1]
                : null;
        if (includeTemperature &&
            temperature is null &&
            _profile.TemperatureQuery is string temperatureQuery)
        {
            temperature = FirstNumber(
                await QueryAsync(temperatureQuery, cancellationToken).ConfigureAwait(false),
                temperatureQuery);
        }

        return new Measurement(
            channel,
            sequence,
            DateTimeOffset.UtcNow,
            elapsed,
            values[0],
            Settings.Function.Unit(),
            temperature);
    }

    private IEnumerable<string> SelectionCommands(
        AcquisitionSettings settings,
        string path)
    {
        bool automatic = settings.MeasurementRange.Equals(
            "AUTO",
            StringComparison.OrdinalIgnoreCase);
        bool ranged = settings.Function is not (
            MeasurementFunction.Frequency or MeasurementFunction.Period);
        if (_profile.SelectionStyle is
            ScpiSelectionStyle.SenseQuoted or ScpiSelectionStyle.SenseUnquoted)
        {
            yield return _profile.SelectionStyle == ScpiSelectionStyle.SenseQuoted
                ? $"SENS:FUNC \"{path}\""
                : $"SENS:FUNC {path}";
            string? template = automatic
                ? _profile.AutoRangeTemplate
                : _profile.RangeTemplate;
            if (ranged && template is not null)
            {
                yield return Expand(template, path, settings);
            }

            yield break;
        }

        string rangeSuffix = !automatic
            ? $" {settings.MeasurementRange}"
            : _profile.AutoInConfigure && ranged
                ? " AUTO"
                : string.Empty;
        yield return $"CONF:{path}{rangeSuffix}";
        if (automatic && ranged && _profile.AutoRangeTemplate is string autoRange)
        {
            yield return Expand(autoRange, path, settings);
        }
    }

    private static string Expand(
        string template,
        string path,
        AcquisitionSettings settings) =>
        template
            .Replace("{path}", path, StringComparison.Ordinal)
            .Replace("{range}", settings.MeasurementRange, StringComparison.Ordinal)
            .Replace(
                "{nplc}",
                settings.Nplc.ToString("G9", CultureInfo.InvariantCulture),
                StringComparison.Ordinal)
            .Replace(
                "{autozero}",
                settings.Autozero.ToUpperInvariant(),
                StringComparison.Ordinal);

    private static Dictionary<InstrumentModel, ScpiDmmProfile> CreateProfiles() =>
        new Dictionary<InstrumentModel, ScpiDmmProfile>
        {
            [InstrumentModel.Keysight34465A] = new(
                InstrumentModel.Keysight34465A,
                LineFrequencyQuery: "SYST:LFREQ?"),
            [InstrumentModel.Keysight34470A] = new(
                InstrumentModel.Keysight34470A,
                LineFrequencyQuery: "SYST:LFREQ?"),
            [InstrumentModel.Fluke8588A] = new(
                InstrumentModel.Fluke8588A,
                AutozeroTemplate: null,
                LineFrequencyQuery: "SYST:LFREQ?",
                ErrorQuery: "SYST:ERR:NEXT?",
                TemperatureQuery: "SYST:TEMP?",
                TriggerCommands:
                [
                    "TRIG:RESET",
                    "TRIG:SOUR IMM",
                    "TRIG:COUN 1",
                ]),
            [InstrumentModel.Fluke8846A] = new(
                InstrumentModel.Fluke8846A,
                NplcTemplate: "{path}:NPLC {nplc}",
                AutozeroTemplate: "ZERO:AUTO {autozero}"),
            [InstrumentModel.KeithleyDmm7510] = new(
                InstrumentModel.KeithleyDmm7510,
                SelectionStyle: ScpiSelectionStyle.SenseQuoted,
                AutozeroTemplate: "SENS:{path}:AZER {autozero}"),
            [InstrumentModel.RohdeSchwarzHmc8012] = new(
                InstrumentModel.RohdeSchwarzHmc8012,
                AutoInConfigure: true,
                AutoRangeTemplate: null),
            [InstrumentModel.RigolDm3068] = new(InstrumentModel.RigolDm3068),
            [InstrumentModel.SiglentSdm3065X] = new(InstrumentModel.SiglentSdm3065X),
            [InstrumentModel.GwInstekGdm9061] = new(InstrumentModel.GwInstekGdm9061),
            [InstrumentModel.HiokiDm7276] = new(
                InstrumentModel.HiokiDm7276,
                SelectionStyle: ScpiSelectionStyle.SenseUnquoted,
                TemperatureReadQuery: "READ? TEMP"),
            [InstrumentModel.YokogawaDm7560] = new(InstrumentModel.YokogawaDm7560),
            [InstrumentModel.PicotestM3510A] = new(InstrumentModel.PicotestM3510A),
        };
}
