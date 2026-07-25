using System.Data.Common;
using System.Globalization;
using Microsoft.Data.Sqlite;
using PrecisionLab.Domain;

namespace PrecisionLab.Storage;

public sealed class SqliteSessionStore : ISessionStore
{
    private readonly SemaphoreSlim _initializeGate = new(1, 1);
    private readonly SemaphoreSlim _operationGate = new(1, 1);
    private SqliteConnection? _connection;
    private bool _initialized;
    private bool _disposed;

    public SqliteSessionStore(string databasePath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(databasePath);
        DatabasePath = Path.GetFullPath(databasePath);
    }

    public string DatabasePath { get; }

    public async ValueTask InitializeAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_initialized)
        {
            return;
        }

        await _initializeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_initialized)
            {
                return;
            }

            string? directory = Path.GetDirectoryName(DatabasePath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            var connectionString = new SqliteConnectionStringBuilder
            {
                DataSource = DatabasePath,
                Mode = SqliteOpenMode.ReadWriteCreate,
                Cache = SqliteCacheMode.Shared,
            }.ToString();
            _connection = new SqliteConnection(connectionString);
            await _connection.OpenAsync(cancellationToken).ConfigureAwait(false);

            await ExecuteNonQueryAsync(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                PRAGMA foreign_keys=ON;
                PRAGMA busy_timeout=5000;

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    channel INTEGER NOT NULL,
                    instrument_model INTEGER NOT NULL,
                    measurement_function INTEGER NOT NULL,
                    resource TEXT NOT NULL,
                    reported_model TEXT NOT NULL,
                    firmware TEXT NOT NULL,
                    options TEXT NOT NULL,
                    line_frequency_hz REAL NOT NULL,
                    started_utc_ticks INTEGER NOT NULL,
                    ended_utc_ticks INTEGER NULL,
                    status INTEGER NOT NULL,
                    unit INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    committed_sequence INTEGER NOT NULL DEFAULT -1,
                    error TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS samples (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    timestamp_utc_ticks INTEGER NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    value REAL NOT NULL,
                    unit INTEGER NOT NULL,
                    temperature_c REAL NULL,
                    PRIMARY KEY (session_id, sequence),
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS ix_samples_session_time
                    ON samples(session_id, timestamp_utc_ticks);
                """,
                cancellationToken).ConfigureAwait(false);

            await using SqliteCommand recover = Connection.CreateCommand();
            recover.CommandText =
                """
                UPDATE sessions
                SET status = $interrupted,
                    ended_utc_ticks = $ended,
                    error = COALESCE(error, 'Acquisition service stopped before finalization.')
                WHERE status = $running;
                """;
            recover.Parameters.AddWithValue(
                "$interrupted",
                (int)SessionCompletionStatus.Interrupted);
            recover.Parameters.AddWithValue("$ended", DateTimeOffset.UtcNow.UtcTicks);
            recover.Parameters.AddWithValue("$running", (int)SessionCompletionStatus.Running);
            await recover.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            _initialized = true;
        }
        finally
        {
            _initializeGate.Release();
        }
    }

    public async ValueTask<Guid> BeginSessionAsync(
        ChannelId channel,
        AcquisitionSettings settings,
        InstrumentIdentity identity,
        DateTimeOffset startedUtc,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(identity);
        await InitializeAsync(cancellationToken).ConfigureAwait(false);

        Guid id = Guid.NewGuid();
        await _operationGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using SqliteCommand command = Connection.CreateCommand();
            command.CommandText =
                """
                INSERT INTO sessions (
                    id, channel, instrument_model, measurement_function, resource,
                    reported_model, firmware, options, line_frequency_hz,
                    started_utc_ticks, status, unit)
                VALUES (
                    $id, $channel, $model, $function, $resource,
                    $reported, $firmware, $options, $lineFrequency,
                    $started, $status, $unit);
                """;
            command.Parameters.AddWithValue("$id", id.ToString("D", CultureInfo.InvariantCulture));
            command.Parameters.AddWithValue("$channel", (int)channel);
            command.Parameters.AddWithValue("$model", (int)settings.InstrumentModel);
            command.Parameters.AddWithValue("$function", (int)settings.Function);
            command.Parameters.AddWithValue("$resource", settings.Resource);
            command.Parameters.AddWithValue("$reported", identity.ReportedModel);
            command.Parameters.AddWithValue("$firmware", identity.Firmware);
            command.Parameters.AddWithValue("$options", identity.Options);
            command.Parameters.AddWithValue("$lineFrequency", identity.LineFrequencyHz);
            command.Parameters.AddWithValue("$started", startedUtc.UtcTicks);
            command.Parameters.AddWithValue("$status", (int)SessionCompletionStatus.Running);
            command.Parameters.AddWithValue("$unit", (int)settings.Function.Unit());
            await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            return id;
        }
        finally
        {
            _operationGate.Release();
        }
    }

    public ValueTask AppendAsync(
        Guid sessionId,
        Measurement measurement,
        CancellationToken cancellationToken) =>
        AppendBatchAsync(sessionId, [measurement], cancellationToken);

    public async ValueTask AppendBatchAsync(
        Guid sessionId,
        IReadOnlyList<Measurement> measurements,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(measurements);
        if (measurements.Count == 0)
        {
            return;
        }

        long expected = measurements[0].Sequence;
        foreach (Measurement measurement in measurements)
        {
            ArgumentNullException.ThrowIfNull(measurement);
            if (measurement.Sequence != expected)
            {
                throw new InvalidDataException(
                    $"Batch sequence {measurement.Sequence} is not contiguous with {expected - 1}.");
            }

            expected++;
        }

        await InitializeAsync(cancellationToken).ConfigureAwait(false);
        await _operationGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using DbTransaction transaction =
                await Connection.BeginTransactionAsync(cancellationToken).ConfigureAwait(false);
            foreach (Measurement measurement in measurements)
            {
                await using SqliteCommand insert = Connection.CreateCommand();
                insert.Transaction = (SqliteTransaction)transaction;
                insert.CommandText =
                    """
                    INSERT INTO samples (
                        session_id, sequence, timestamp_utc_ticks, elapsed_seconds,
                        value, unit, temperature_c)
                    VALUES (
                        $session, $sequence, $timestamp, $elapsed,
                        $value, $unit, $temperature);
                    """;
                AddMeasurementParameters(insert, sessionId, measurement);
                await insert.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            await using SqliteCommand update = Connection.CreateCommand();
            update.Transaction = (SqliteTransaction)transaction;
            update.CommandText =
                """
                UPDATE sessions
                SET sample_count = sample_count + $count,
                    committed_sequence = $sequence
                WHERE id = $session
                  AND committed_sequence = $previous;
                """;
            update.Parameters.AddWithValue("$count", measurements.Count);
            update.Parameters.AddWithValue("$sequence", measurements[^1].Sequence);
            update.Parameters.AddWithValue("$previous", measurements[0].Sequence - 1);
            update.Parameters.AddWithValue(
                "$session",
                sessionId.ToString("D", CultureInfo.InvariantCulture));
            int updated = await update.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            if (updated != 1)
            {
                throw new InvalidDataException(
                    $"Session {sessionId:D} rejected batch starting at " +
                    $"{measurements[0].Sequence}.");
            }

            await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _operationGate.Release();
        }
    }

    public async ValueTask CompleteSessionAsync(
        Guid sessionId,
        SessionCompletionStatus status,
        string? error,
        CancellationToken cancellationToken)
    {
        if (status == SessionCompletionStatus.Running)
        {
            throw new ArgumentException("A completed session cannot remain Running.", nameof(status));
        }

        await InitializeAsync(cancellationToken).ConfigureAwait(false);
        await _operationGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using SqliteCommand command = Connection.CreateCommand();
            command.CommandText =
                """
                UPDATE sessions
                SET status = $status,
                    ended_utc_ticks = $ended,
                    error = $error
                WHERE id = $id;
                """;
            command.Parameters.AddWithValue("$status", (int)status);
            command.Parameters.AddWithValue("$ended", DateTimeOffset.UtcNow.UtcTicks);
            command.Parameters.AddWithValue("$error", (object?)error ?? DBNull.Value);
            command.Parameters.AddWithValue(
                "$id",
                sessionId.ToString("D", CultureInfo.InvariantCulture));
            await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _operationGate.Release();
        }
    }

    public async ValueTask<IReadOnlyList<SessionInfo>> ListSessionsAsync(
        int limit,
        CancellationToken cancellationToken)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(limit);
        await InitializeAsync(cancellationToken).ConfigureAwait(false);
        await _operationGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using SqliteCommand command = Connection.CreateCommand();
            command.CommandText =
                """
                SELECT id, channel, instrument_model, measurement_function, resource,
                       started_utc_ticks, ended_utc_ticks, status, unit,
                       sample_count, committed_sequence, error
                FROM sessions
                ORDER BY started_utc_ticks DESC
                LIMIT $limit;
                """;
            command.Parameters.AddWithValue("$limit", limit);
            await using SqliteDataReader reader =
                await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
            var sessions = new List<SessionInfo>();
            while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
            {
                sessions.Add(ReadSession(reader));
            }

            return sessions;
        }
        finally
        {
            _operationGate.Release();
        }
    }

    public async ValueTask<IReadOnlyList<Measurement>> ReadMeasurementsAsync(
        Guid sessionId,
        long firstSequence,
        int limit,
        CancellationToken cancellationToken)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(firstSequence);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(limit);
        await InitializeAsync(cancellationToken).ConfigureAwait(false);
        await _operationGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ChannelId channel = await ReadSessionChannelAsync(
                sessionId,
                cancellationToken).ConfigureAwait(false);
            await using SqliteCommand command = Connection.CreateCommand();
            command.CommandText =
                """
                SELECT sequence, timestamp_utc_ticks, elapsed_seconds,
                       value, unit, temperature_c
                FROM samples
                WHERE session_id = $session AND sequence >= $first
                ORDER BY sequence
                LIMIT $limit;
                """;
            command.Parameters.AddWithValue(
                "$session",
                sessionId.ToString("D", CultureInfo.InvariantCulture));
            command.Parameters.AddWithValue("$first", firstSequence);
            command.Parameters.AddWithValue("$limit", limit);
            await using SqliteDataReader reader =
                await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
            var output = new List<Measurement>();
            while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
            {
                output.Add(
                    new Measurement(
                        channel,
                        reader.GetInt64(0),
                        new DateTimeOffset(reader.GetInt64(1), TimeSpan.Zero),
                        TimeSpan.FromSeconds(reader.GetDouble(2)),
                        reader.GetDouble(3),
                        (MeasurementUnit)reader.GetInt32(4),
                        reader.IsDBNull(5) ? null : reader.GetDouble(5)));
            }

            return output;
        }
        finally
        {
            _operationGate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        if (_connection is not null)
        {
            await _connection.DisposeAsync().ConfigureAwait(false);
            _connection = null;
        }

        _initializeGate.Dispose();
        _operationGate.Dispose();
    }

    private SqliteConnection Connection =>
        _connection ?? throw new InvalidOperationException("The session store is not initialized.");

    private async Task ExecuteNonQueryAsync(
        string sql,
        CancellationToken cancellationToken)
    {
        await using SqliteCommand command = Connection.CreateCommand();
        command.CommandText = sql;
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static void AddMeasurementParameters(
        SqliteCommand command,
        Guid sessionId,
        Measurement measurement)
    {
        command.Parameters.AddWithValue(
            "$session",
            sessionId.ToString("D", CultureInfo.InvariantCulture));
        command.Parameters.AddWithValue("$sequence", measurement.Sequence);
        command.Parameters.AddWithValue("$timestamp", measurement.TimestampUtc.UtcTicks);
        command.Parameters.AddWithValue("$elapsed", measurement.Elapsed.TotalSeconds);
        command.Parameters.AddWithValue("$value", measurement.Value);
        command.Parameters.AddWithValue("$unit", (int)measurement.Unit);
        command.Parameters.AddWithValue(
            "$temperature",
            (object?)measurement.InternalTemperatureC ?? DBNull.Value);
    }

    private static SessionInfo ReadSession(SqliteDataReader reader) =>
        new(
            Guid.Parse(reader.GetString(0)),
            (ChannelId)reader.GetInt32(1),
            (InstrumentModel)reader.GetInt32(2),
            (MeasurementFunction)reader.GetInt32(3),
            reader.GetString(4),
            new DateTimeOffset(reader.GetInt64(5), TimeSpan.Zero),
            reader.IsDBNull(6)
                ? null
                : new DateTimeOffset(reader.GetInt64(6), TimeSpan.Zero),
            (SessionCompletionStatus)reader.GetInt32(7),
            (MeasurementUnit)reader.GetInt32(8),
            reader.GetInt64(9),
            reader.GetInt64(10),
            reader.IsDBNull(11) ? null : reader.GetString(11));

    private async Task<ChannelId> ReadSessionChannelAsync(
        Guid sessionId,
        CancellationToken cancellationToken)
    {
        await using SqliteCommand command = Connection.CreateCommand();
        command.CommandText = "SELECT channel FROM sessions WHERE id = $id;";
        command.Parameters.AddWithValue(
            "$id",
            sessionId.ToString("D", CultureInfo.InvariantCulture));
        object? value = await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false);
        return value is long channel
            ? (ChannelId)channel
            : throw new KeyNotFoundException($"Session {sessionId:D} was not found.");
    }
}
