using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using PrecisionLab.Domain;
using PrecisionLab.Storage;

namespace PrecisionLab.Export;

public sealed record ImportedMeasurementData(
    double[] ElapsedSeconds,
    double[] Values,
    string XColumn,
    string YColumn,
    string Unit);

public static partial class CsvDataExchange
{
    private static readonly string[] LineSeparators = ["\r\n", "\n"];

    private static readonly char[] CandidateDelimiters = [',', '\t', ';'];

    private static readonly string[] TimeHints =
        ["time", "timestamp", "date", "elapsed", "second", "时间", "秒"];

    private static readonly string[] ValueHints =
    [
        "value",
        "reading",
        "measurement",
        "voltage",
        "current",
        "resistance",
        "dmm",
        "值",
        "读数",
        "电压",
        "电流",
        "电阻",
    ];

    public static async Task<ImportedMeasurementData> ImportAsync(
        string path,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        string text = await File.ReadAllTextAsync(
            path,
            Encoding.UTF8,
            cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new InvalidDataException("The CSV file is empty.");
        }

        char delimiter = DetectDelimiter(text);
        string[] lines = text
            .Split(LineSeparators, StringSplitOptions.RemoveEmptyEntries);
        if (lines.Length < 2)
        {
            throw new InvalidDataException("The CSV needs a header and at least one row.");
        }

        string[] headers = ParseRow(lines[0], delimiter).ToArray();
        var columns = headers.Select(_ => new List<string>()).ToArray();
        for (int line = 1; line < lines.Length; line++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            List<string> row = ParseRow(lines[line], delimiter);
            for (int column = 0; column < headers.Length; column++)
            {
                columns[column].Add(column < row.Count ? row[column] : string.Empty);
            }
        }

        NumericColumn[] numeric = columns.Select(ParseNumericColumn).ToArray();
        int valueIndex = ChooseColumn(headers, numeric, ValueHints, excluded: -1);
        int timeIndex = ChooseColumn(headers, numeric, TimeHints, excluded: valueIndex);
        if (valueIndex < 0)
        {
            throw new InvalidDataException("No numeric measurement column was found.");
        }

        double[] values = numeric[valueIndex].Values;
        double[] elapsed = timeIndex >= 0
            ? numeric[timeIndex].Values
            : Enumerable.Range(0, values.Length).Select(index => (double)index).ToArray();
        var valid = Enumerable.Range(0, values.Length)
            .Where(index =>
                double.IsFinite(values[index]) &&
                index < elapsed.Length &&
                double.IsFinite(elapsed[index]))
            .ToArray();
        if (valid.Length == 0)
        {
            throw new InvalidDataException("The selected CSV columns contain no valid pairs.");
        }

        double first = elapsed[valid[0]];
        double[] outputElapsed = valid.Select(index => elapsed[index] - first).ToArray();
        double[] outputValues = valid.Select(index => values[index]).ToArray();
        string unit = UnitPattern().Match(headers[valueIndex]) is Match { Success: true } match
            ? match.Groups[1].Value.Trim()
            : "V";
        return new ImportedMeasurementData(
            outputElapsed,
            outputValues,
            timeIndex >= 0 ? headers[timeIndex] : "index",
            headers[valueIndex],
            unit);
    }

    public static async Task ExportSessionAsync(
        string path,
        Guid sessionId,
        ISessionStore store,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(store);
        SessionInfo session = (await store.ListSessionsAsync(
                10_000,
                cancellationToken).ConfigureAwait(false))
            .Single(item => item.Id == sessionId);

        await using var stream = new FileStream(
            path,
            FileMode.Create,
            FileAccess.Write,
            FileShare.Read,
            64 * 1_024,
            FileOptions.Asynchronous);
        await using var writer = new StreamWriter(
            stream,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        await writer.WriteLineAsync(
            "timestamp_iso,elapsed_s,reading,unit,internal_temperature_c," +
            "channel,instrument_model,resource,session_id").ConfigureAwait(false);

        const int pageSize = 8_192;
        long firstSequence = 0;
        while (true)
        {
            IReadOnlyList<Measurement> page = await store.ReadMeasurementsAsync(
                sessionId,
                firstSequence,
                pageSize,
                cancellationToken).ConfigureAwait(false);
            if (page.Count == 0)
            {
                break;
            }

            foreach (Measurement measurement in page)
            {
                cancellationToken.ThrowIfCancellationRequested();
                string temperature = measurement.InternalTemperatureC is double value
                    ? value.ToString("G17", CultureInfo.InvariantCulture)
                    : string.Empty;
                string row = string.Join(
                    ',',
                    Escape(measurement.TimestampUtc.ToString("O", CultureInfo.InvariantCulture)),
                    measurement.Elapsed.TotalSeconds.ToString("G17", CultureInfo.InvariantCulture),
                    measurement.Value.ToString("G17", CultureInfo.InvariantCulture),
                    Escape(measurement.Unit.Symbol()),
                    temperature,
                    measurement.Channel.ToString(),
                    session.InstrumentModel.ToString(),
                    Escape(session.Resource),
                    sessionId.ToString("D", CultureInfo.InvariantCulture));
                await writer.WriteLineAsync(row).ConfigureAwait(false);
            }

            firstSequence = page[^1].Sequence + 1;
            if (page.Count < pageSize)
            {
                break;
            }
        }

        await writer.FlushAsync(cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        stream.Flush(flushToDisk: true);
    }

    private static int ChooseColumn(
        string[] headers,
        NumericColumn[] numeric,
        string[] hints,
        int excluded)
    {
        return Enumerable.Range(0, headers.Length)
            .Where(index => index != excluded && numeric[index].ValidRatio >= 0.5)
            .OrderByDescending(index => ScoreHeader(headers[index], hints))
            .ThenByDescending(index => numeric[index].ValidRatio)
            .Cast<int?>()
            .FirstOrDefault() ?? -1;
    }

    private static int ScoreHeader(string header, string[] hints)
    {
        string lowered = header.ToLowerInvariant();
        int score = 0;
        foreach (string hint in hints)
        {
            if (lowered == hint)
            {
                score = Math.Max(score, 4);
            }
            else if (lowered.Contains(hint, StringComparison.Ordinal))
            {
                score = Math.Max(score, 2);
            }
        }

        return score;
    }

    private static NumericColumn ParseNumericColumn(List<string> values)
    {
        var output = Enumerable.Repeat(double.NaN, values.Count).ToArray();
        int valid = 0;
        for (int index = 0; index < values.Count; index++)
        {
            string text = values[index].Trim();
            if (double.TryParse(
                    text,
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out double number))
            {
                output[index] = number;
                valid++;
            }
            else if (DateTimeOffset.TryParse(
                         text,
                         CultureInfo.InvariantCulture,
                         DateTimeStyles.AssumeUniversal,
                         out DateTimeOffset timestamp))
            {
                output[index] = timestamp.ToUnixTimeMilliseconds() / 1_000.0;
                valid++;
            }
        }

        return new NumericColumn(output, valid / (double)Math.Max(1, values.Count));
    }

    private static char DetectDelimiter(string text)
    {
        string firstLine = text.Split(LineSeparators, StringSplitOptions.None)[0];
        return CandidateDelimiters
            .OrderByDescending(delimiter => firstLine.Count(character => character == delimiter))
            .First();
    }

    private static List<string> ParseRow(string line, char delimiter)
    {
        var fields = new List<string>();
        var current = new StringBuilder();
        bool quoted = false;
        for (int index = 0; index < line.Length; index++)
        {
            char character = line[index];
            if (character == '"')
            {
                if (quoted && index + 1 < line.Length && line[index + 1] == '"')
                {
                    current.Append('"');
                    index++;
                }
                else
                {
                    quoted = !quoted;
                }
            }
            else if (character == delimiter && !quoted)
            {
                fields.Add(current.ToString());
                current.Clear();
            }
            else
            {
                current.Append(character);
            }
        }

        fields.Add(current.ToString());
        return fields;
    }

    private static string Escape(string value) =>
        value.IndexOfAny([',', '"', '\r', '\n']) >= 0
            ? $"\"{value.Replace("\"", "\"\"", StringComparison.Ordinal)}\""
            : value;

    [GeneratedRegex(@"(?:\(|\[)\s*([^\)\]]+)\s*(?:\)|\])")]
    private static partial Regex UnitPattern();

    private sealed record NumericColumn(double[] Values, double ValidRatio);
}
