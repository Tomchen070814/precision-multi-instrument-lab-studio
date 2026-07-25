using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Core.Tests;

public sealed class DataFrameCodecTests
{
    [Fact]
    public async Task MeasurementFrameRoundTripsWithoutNumericLoss()
    {
        var expected = new Measurement(
            ChannelId.C,
            9_223_372,
            new DateTimeOffset(2026, 7, 25, 9, 10, 11, TimeSpan.Zero),
            TimeSpan.FromSeconds(123.456789),
            -1.234567890123,
            MeasurementUnit.Ohm,
            23.125);
        await using var stream = new MemoryStream();

        await DataFrameCodec.WriteMeasurementAsync(
            stream,
            expected,
            CancellationToken.None);
        stream.Position = 0;
        Measurement actual = await DataFrameCodec.ReadMeasurementAsync(
            stream,
            CancellationToken.None);

        Assert.Equal(expected, actual);
    }

    [Fact]
    public async Task MeasurementFramePreservesMissingTemperature()
    {
        var expected = new Measurement(
            ChannelId.A,
            0,
            DateTimeOffset.UnixEpoch,
            TimeSpan.Zero,
            10,
            MeasurementUnit.Volt,
            null);
        await using var stream = new MemoryStream();

        await DataFrameCodec.WriteMeasurementAsync(
            stream,
            expected,
            CancellationToken.None);
        stream.Position = 0;

        Assert.Null(
            (await DataFrameCodec.ReadMeasurementAsync(stream, CancellationToken.None))
            .InternalTemperatureC);
    }
}
