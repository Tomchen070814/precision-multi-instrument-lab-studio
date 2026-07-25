using System.IO.Compression;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PrecisionLab.Domain;

namespace PrecisionLab.Export;

public static class DiagnosticReportWriter
{
    private static readonly JsonSerializerOptions JsonOptions = CreateJsonOptions();

    public static async Task<string> CreateAsync(
        string outputPath,
        ServiceSnapshot snapshot,
        string databasePath,
        string language,
        IReadOnlyList<string>? recentEvents = null,
        IReadOnlyList<string>? logFiles = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);
        ArgumentNullException.ThrowIfNull(snapshot);
        string finalPath = Path.ChangeExtension(Path.GetFullPath(outputPath), ".zip") ??
            throw new InvalidOperationException("Could not create the diagnostic ZIP path.");
        string? directory = Path.GetDirectoryName(finalPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        string temporary = $"{finalPath}.{Environment.ProcessId}.tmp";
        var payload = new
        {
            schemaVersion = 1,
            generatedAtUtc = DateTimeOffset.UtcNow,
            language,
            system = new
            {
                operatingSystem = RuntimeInformation.OSDescription,
                architecture = RuntimeInformation.OSArchitecture.ToString(),
                framework = RuntimeInformation.FrameworkDescription,
                processArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            },
            application = new
            {
                snapshot.ProtocolVersion,
                snapshot.ServiceVersion,
                snapshot.ServiceStartedUtc,
                snapshot.ServiceProcessId,
                snapshot.ServiceWorkingSetBytes,
                databaseFile = Path.GetFileName(databasePath),
            },
            channels = snapshot.Channels,
            recentEvents = recentEvents ?? [],
            note = "Measurement samples are intentionally excluded.",
        };

        try
        {
            await using (FileStream stream = new(
                             temporary,
                             FileMode.CreateNew,
                             FileAccess.ReadWrite,
                             FileShare.None,
                             64 * 1_024,
                             FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                using (var archive = new ZipArchive(
                           stream,
                           ZipArchiveMode.Create,
                           leaveOpen: true))
                {
                    await WriteEntryAsync(
                        archive,
                        "diagnostic.json",
                        JsonSerializer.Serialize(payload, JsonOptions),
                        cancellationToken).ConfigureAwait(false);
                    await WriteEntryAsync(
                        archive,
                        "diagnostic.html",
                        BuildHtml(payload),
                        cancellationToken).ConfigureAwait(false);
                    await WriteEntryAsync(
                        archive,
                        "README.txt",
                        """
                        Open diagnostic.html for the summary. Logs contain runtime events and
                        errors. Measurement samples are not included in this report.

                        打开 diagnostic.html 查看摘要。日志包含运行事件与错误。
                        本诊断包不包含测量样本。
                        """,
                        cancellationToken).ConfigureAwait(false);

                    foreach (string logFile in logFiles ?? [])
                    {
                        if (!File.Exists(logFile))
                        {
                            continue;
                        }

                        ZipArchiveEntry entry = archive.CreateEntry(
                            $"logs/{Path.GetFileName(logFile)}",
                            CompressionLevel.Optimal);
                        await using Stream destination = entry.Open();
                        await using FileStream source = File.OpenRead(logFile);
                        await source.CopyToAsync(
                            destination,
                            cancellationToken).ConfigureAwait(false);
                    }
                }

                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }

            File.Move(temporary, finalPath, overwrite: true);
            return finalPath;
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    private static async Task WriteEntryAsync(
        ZipArchive archive,
        string name,
        string content,
        CancellationToken cancellationToken)
    {
        ZipArchiveEntry entry = archive.CreateEntry(name, CompressionLevel.Optimal);
        await using Stream stream = entry.Open();
        await using var writer = new StreamWriter(
            stream,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
            bufferSize: 1_024,
            leaveOpen: false);
        await writer.WriteAsync(content.AsMemory(), cancellationToken).ConfigureAwait(false);
    }

    private static string BuildHtml(object payload)
    {
        string json = JsonSerializer.Serialize(payload, JsonOptions);
        return
            """
            <!doctype html>
            <html><head><meta charset="utf-8">
            <title>PrecisionLab Diagnostic Report</title>
            <style>
            body{font-family:Segoe UI,Arial,sans-serif;margin:36px;color:#18212b;background:#f7f9fb}
            section{background:white;border:1px solid #dfe5eb;border-radius:10px;padding:18px}
            pre{white-space:pre-wrap;word-break:break-word;font:12px/1.55 Consolas,monospace}
            </style></head><body><h1>PrecisionLab Diagnostic Report</h1><section><pre>
            """ +
            WebUtility.HtmlEncode(json) +
            "</pre></section></body></html>";
    }

    private static JsonSerializerOptions CreateJsonOptions()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web)
        {
            WriteIndented = true,
        };
        options.Converters.Add(new JsonStringEnumConverter());
        return options;
    }
}
