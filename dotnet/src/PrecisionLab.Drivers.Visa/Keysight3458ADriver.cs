using System.Globalization;
using PrecisionLab.Domain;
using PrecisionLab.Drivers.Abstractions;

namespace PrecisionLab.Drivers.Visa;

public sealed class Keysight3458ADriver : VisaInstrumentDriverBase, IBurstInstrumentDriver
{
    public Keysight3458ADriver(
        AcquisitionSettings settings,
        IVisaBackend backend,
        TimeProvider? timeProvider = null)
        : base(InstrumentModel.Keysight3458A, settings, backend, timeProvider)
    {
    }

    public override async ValueTask<InstrumentIdentity> ConnectAsync(
        CancellationToken cancellationToken)
    {
        if (!VisaDriverUtilities.IsGpibInstrument(Resource))
        {
            throw new InstrumentDriverException(
                "The 3458A requires a GPIB VISA resource such as GPIB0::22::INSTR.");
        }

        try
        {
            await OpenSessionAsync(cancellationToken).ConfigureAwait(false);
            RequireSession().TimeoutMilliseconds = 15_000;
            try
            {
                await RequireSession().ClearAsync(cancellationToken).ConfigureAwait(false);
            }
            catch
            {
                // Some mixed NI/Keysight installations reject SDC while normal
                // reads and writes remain functional. ID? is authoritative.
            }

            await WriteAsync("END ALWAYS", cancellationToken).ConfigureAwait(false);
            string model = await QueryAsync("ID?", cancellationToken).ConfigureAwait(false);
            if (!model.Contains("3458", StringComparison.OrdinalIgnoreCase))
            {
                throw new InstrumentDriverException(
                    $"{Resource} reported '{model}', not a 3458A.");
            }

            string firmware = await QueryAsync("REV?", cancellationToken).ConfigureAwait(false);
            string options = await QueryAsync("OPT?", cancellationToken).ConfigureAwait(false);
            string line = await QueryAsync("LINE?", cancellationToken).ConfigureAwait(false);
            double[] lineValues = VisaDriverUtilities.ParseNumbers(line);
            double lineFrequency = lineValues.Length > 0 ? lineValues[0] : 50;
            Identity = new InstrumentIdentity(
                InstrumentModel.Keysight3458A,
                model,
                Resource,
                firmware,
                options,
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
        if (settings.Function is MeasurementFunction.DigitizeDc or MeasurementFunction.DigitizeAc)
        {
            throw new InstrumentDriverException(
                "Use burst acquisition for 3458A DSDC or DSAC modes.");
        }

        string command = string.Join(
            ';',
            "PRESET NORM",
            "END ALWAYS",
            "OFORMAT ASCII",
            $"{VisaDriverUtilities.LegacyFunctionCommand(settings.Function)} {settings.MeasurementRange}",
            $"NPLC {settings.Nplc.ToString("G9", CultureInfo.InvariantCulture)}",
            $"NDIG {settings.Digits.ToString(CultureInfo.InvariantCulture)}",
            $"AZERO {settings.Autozero.ToUpperInvariant()}");
        IVisaMessageSession session = RequireSession();
        double lineFrequency = Identity?.LineFrequencyHz ?? 50;
        session.TimeoutMilliseconds = Math.Max(
            15_000,
            checked((int)((settings.Nplc / Math.Max(lineFrequency, 1) + 8) * 1_000)));
        await WriteAsync(command, cancellationToken).ConfigureAwait(false);
        int error = (int)FirstNumber(
            await QueryAsync("ERR?", cancellationToken).ConfigureAwait(false),
            "ERR?");
        if (error != 0)
        {
            throw new InstrumentDriverException($"3458A configuration error ERR={error}.");
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
        await WriteAsync("TRIG SGL", cancellationToken).ConfigureAwait(false);
        string payload = await ReadOnlyAsync(cancellationToken).ConfigureAwait(false);
        double value = FirstNumber(payload, "TRIG SGL");
        double? temperature = null;
        if (includeTemperature)
        {
            temperature = FirstNumber(
                await QueryAsync("TEMP?", cancellationToken).ConfigureAwait(false),
                "TEMP?");
        }

        return new Measurement(
            channel,
            sequence,
            DateTimeOffset.UtcNow,
            elapsed,
            value,
            Settings.Function.Unit(),
            temperature);
    }

    public async ValueTask<IReadOnlyList<Measurement>> AcquireBurstAsync(
        ChannelId channel,
        long firstSequence,
        BurstAcquisitionSettings settings,
        CancellationToken cancellationToken)
    {
        if (settings.Count is < 1 or > 148_000)
        {
            throw new ArgumentOutOfRangeException(
                nameof(settings),
                "Burst count must be between 1 and 148000.");
        }

        if (settings.Interval < TimeSpan.FromMicroseconds(10))
        {
            throw new ArgumentOutOfRangeException(
                nameof(settings),
                "Burst interval must be at least 10 µs in stable ASCII transfer mode.");
        }

        if (settings.Aperture < TimeSpan.FromTicks(5) ||
            settings.Aperture > TimeSpan.FromSeconds(1) ||
            settings.Interval < settings.Aperture)
        {
            throw new ArgumentOutOfRangeException(
                nameof(settings),
                "Aperture must be 500 ns to 1 s and not exceed the interval.");
        }

        if (settings.Function is not (
            MeasurementFunction.DigitizeDc or MeasurementFunction.DigitizeAc))
        {
            throw new ArgumentException(
                "Burst mode requires DigitizeDc or DigitizeAc.",
                nameof(settings));
        }

        IVisaMessageSession session = RequireSession();
        double interval = settings.Interval.TotalSeconds;
        double aperture = settings.Aperture.TotalSeconds;
        session.TimeoutMilliseconds = Math.Max(
            30_000,
            checked((int)((settings.Count * interval + 12) * 1_000)));
        string command = string.Join(
            ';',
            "PRESET FAST",
            "END ON",
            "OFORMAT ASCII",
            "MFORMAT SREAL",
            "MEM FIFO",
            "TARM HOLD",
            "TRIG HOLD",
            $"{VisaDriverUtilities.LegacyFunctionCommand(settings.Function)} {settings.MeasurementRange}",
            $"APER {aperture.ToString("G9", CultureInfo.InvariantCulture)}",
            $"NRDGS {settings.Count.ToString(CultureInfo.InvariantCulture)},TIMER",
            $"TIMER {interval.ToString("G9", CultureInfo.InvariantCulture)}",
            "TRIG AUTO",
            "TARM SGL");
        try
        {
            await WriteAsync(command, cancellationToken).ConfigureAwait(false);
            await Task.Delay(
                TimeSpan.FromSeconds(Math.Min(settings.Count * interval + 0.25, 10)),
                cancellationToken).ConfigureAwait(false);

            int available = 0;
            DateTimeOffset deadline = DateTimeOffset.UtcNow +
                TimeSpan.FromSeconds(Math.Max(10, settings.Count * interval + 2));
            do
            {
                available = (int)FirstNumber(
                    await QueryAsync("MCOUNT?", cancellationToken).ConfigureAwait(false),
                    "MCOUNT?");
                if (available < settings.Count)
                {
                    await Task.Delay(50, cancellationToken).ConfigureAwait(false);
                }
            }
            while (available < settings.Count && DateTimeOffset.UtcNow < deadline);

            if (available < settings.Count)
            {
                throw new TimeoutException(
                    $"3458A burst timed out with {available}/{settings.Count} samples.");
            }

            string payload = await QueryAsync(
                $"RMEM 1,{settings.Count.ToString(CultureInfo.InvariantCulture)},1",
                cancellationToken).ConfigureAwait(false);
            double[] values = VisaDriverUtilities.ParseNumbers(payload);
            if (values.Length < settings.Count)
            {
                throw new InvalidDataException(
                    $"3458A returned {values.Length}/{settings.Count} burst samples.");
            }

            DateTimeOffset started = DateTimeOffset.UtcNow;
            var output = new Measurement[settings.Count];
            for (int index = 0; index < output.Length; index++)
            {
                TimeSpan elapsed = TimeSpan.FromSeconds(index * interval);
                output[index] = new Measurement(
                    channel,
                    firstSequence + index,
                    started + elapsed,
                    elapsed,
                    values[index],
                    settings.Function.Unit(),
                    null);
            }

            return output;
        }
        finally
        {
            try
            {
                await WriteAsync(
                    "MEM OFF;TRIG HOLD;TARM HOLD;END ALWAYS;OFORMAT ASCII",
                    CancellationToken.None).ConfigureAwait(false);
            }
            catch
            {
                // Best-effort recovery; the caller will close the session.
            }
        }
    }

    public override async ValueTask DisconnectAsync(CancellationToken cancellationToken)
    {
        if (Session is not null)
        {
            try
            {
                await WriteAsync(
                    "TRIG HOLD;TARM HOLD;MEM OFF;DISP ON",
                    cancellationToken).ConfigureAwait(false);
            }
            catch
            {
                // Closing the VISA session remains the final cancellation path.
            }
        }

        await base.DisconnectAsync(cancellationToken).ConfigureAwait(false);
    }

    private async ValueTask<string> ReadOnlyAsync(CancellationToken cancellationToken)
    {
        try
        {
            return (await RequireSession().ReadAsync(cancellationToken).ConfigureAwait(false)).Trim();
        }
        catch (Exception exception)
        {
            throw new InstrumentDriverException(
                $"Read failed on {Resource}: {exception.Message}",
                exception);
        }
    }
}
