using PrecisionLab.Contracts;
using PrecisionLab.Domain;

namespace PrecisionLab.Core.Tests;

public sealed class ProtocolTests
{
    [Fact]
    public async Task ControlFrameRoundTripsWithoutStreamReaderBuffering()
    {
        var expected = new ControlRequest(
            ControlOperations.Start,
            [ChannelId.A, ChannelId.B]);
        await using var stream = new MemoryStream();

        await ControlPipeProtocol.WriteAsync(
            stream,
            expected,
            CancellationToken.None);
        stream.Position = 0;
        ControlRequest actual = await ControlPipeProtocol.ReadAsync<ControlRequest>(
            stream,
            CancellationToken.None);

        Assert.Equal(expected.Operation, actual.Operation);
        Assert.Equal(expected.Channels, actual.Channels);
    }

    [Fact]
    public async Task BinaryMeasurementFrameRoundTrips()
    {
        var expected = new Measurement(
            ChannelId.C,
            42,
            new DateTimeOffset(2026, 7, 25, 1, 2, 3, TimeSpan.Zero),
            TimeSpan.FromSeconds(1.25),
            -1.2345,
            MeasurementUnit.Volt,
            23.4);
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
}
