using System.Text.Json;
using System.Text.Json.Serialization;
using PrecisionLab.Domain;

namespace PrecisionLab.Acquisition;

public sealed class JsonLinesMeasurementSink : IMeasurementSink
{
    private static readonly JsonSerializerOptions JsonOptions = CreateJsonOptions();
    private readonly FileStream _stream;
    private readonly TimeProvider _timeProvider;
    private long _lastFlushTimestamp;
    private bool _disposed;

    public JsonLinesMeasurementSink(string sessionDirectory, TimeProvider? timeProvider = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionDirectory);
        Directory.CreateDirectory(sessionDirectory);
        _timeProvider = timeProvider ?? TimeProvider.System;
        _lastFlushTimestamp = _timeProvider.GetTimestamp();
        SessionPath = Path.Combine(
            sessionDirectory,
            $"precisionlab-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}-{Environment.ProcessId}.jsonl");
        _stream = new FileStream(
            SessionPath,
            new FileStreamOptions
            {
                Access = FileAccess.Write,
                Mode = FileMode.CreateNew,
                Share = FileShare.Read,
                Options = FileOptions.Asynchronous | FileOptions.WriteThrough,
                BufferSize = 64 * 1_024,
            });
    }

    public string SessionPath { get; }

    public async ValueTask WriteAsync(
        Measurement measurement,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        byte[] json = JsonSerializer.SerializeToUtf8Bytes(measurement, JsonOptions);
        await _stream.WriteAsync(json, cancellationToken).ConfigureAwait(false);
        await _stream.WriteAsync("\n"u8.ToArray(), cancellationToken).ConfigureAwait(false);

        if (_timeProvider.GetElapsedTime(_lastFlushTimestamp) >= TimeSpan.FromMilliseconds(100))
        {
            await FlushAsync(cancellationToken).ConfigureAwait(false);
        }
    }

    public async ValueTask FlushAsync(CancellationToken cancellationToken)
    {
        if (_disposed)
        {
            return;
        }

        await _stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        _stream.Flush(flushToDisk: true);
        _lastFlushTimestamp = _timeProvider.GetTimestamp();
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        await FlushAsync(CancellationToken.None).ConfigureAwait(false);
        _disposed = true;
        await _stream.DisposeAsync().ConfigureAwait(false);
    }

    private static JsonSerializerOptions CreateJsonOptions()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);
        options.Converters.Add(new JsonStringEnumConverter());
        return options;
    }
}
