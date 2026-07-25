using System.Buffers.Binary;
using PrecisionLab.Domain;

namespace PrecisionLab.Contracts;

public static class DataFrameCodec
{
    private const uint Magic = 0x42414C50; // "PLAB" in little-endian byte order.
    private const ushort MeasurementFrameType = 1;
    private const int HeaderLength = 12;
    private const int MeasurementPayloadLength = 44;

    public static async ValueTask WriteMeasurementAsync(
        Stream stream,
        Measurement measurement,
        CancellationToken cancellationToken)
    {
        byte[] frame = new byte[HeaderLength + MeasurementPayloadLength];
        Span<byte> header = frame.AsSpan(0, HeaderLength);
        BinaryPrimitives.WriteUInt32LittleEndian(header, Magic);
        BinaryPrimitives.WriteUInt16LittleEndian(header[4..], PipeNames.ProtocolVersion);
        BinaryPrimitives.WriteUInt16LittleEndian(header[6..], MeasurementFrameType);
        BinaryPrimitives.WriteInt32LittleEndian(header[8..], MeasurementPayloadLength);

        Span<byte> payload = frame.AsSpan(HeaderLength);
        payload[0] = (byte)measurement.Channel;
        payload[1] = (byte)measurement.Unit;
        BinaryPrimitives.WriteUInt16LittleEndian(payload[2..], 0);
        BinaryPrimitives.WriteInt64LittleEndian(payload[4..], measurement.Sequence);
        BinaryPrimitives.WriteInt64LittleEndian(
            payload[12..],
            measurement.TimestampUtc.UtcDateTime.Ticks);
        BinaryPrimitives.WriteInt64LittleEndian(
            payload[20..],
            BitConverter.DoubleToInt64Bits(measurement.Elapsed.TotalSeconds));
        BinaryPrimitives.WriteInt64LittleEndian(
            payload[28..],
            BitConverter.DoubleToInt64Bits(measurement.Value));
        BinaryPrimitives.WriteInt64LittleEndian(
            payload[36..],
            BitConverter.DoubleToInt64Bits(measurement.InternalTemperatureC ?? double.NaN));

        await stream.WriteAsync(frame, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
    }

    public static async ValueTask<Measurement> ReadMeasurementAsync(
        Stream stream,
        CancellationToken cancellationToken)
    {
        byte[] header = new byte[HeaderLength];
        await stream.ReadExactlyAsync(header, cancellationToken).ConfigureAwait(false);

        if (BinaryPrimitives.ReadUInt32LittleEndian(header) != Magic)
        {
            throw new InvalidDataException("Invalid PrecisionLab data-frame magic.");
        }

        ushort version = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(4));
        if (version != PipeNames.ProtocolVersion)
        {
            throw new InvalidDataException($"Unsupported data protocol version {version}.");
        }

        ushort frameType = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(6));
        int payloadLength = BinaryPrimitives.ReadInt32LittleEndian(header.AsSpan(8));
        if (frameType != MeasurementFrameType || payloadLength != MeasurementPayloadLength)
        {
            throw new InvalidDataException(
                $"Unsupported frame type {frameType} or payload length {payloadLength}.");
        }

        byte[] payload = new byte[payloadLength];
        await stream.ReadExactlyAsync(payload, cancellationToken).ConfigureAwait(false);
        ReadOnlySpan<byte> body = payload;

        double temperature = BitConverter.Int64BitsToDouble(
            BinaryPrimitives.ReadInt64LittleEndian(body[36..]));

        return new Measurement(
            (ChannelId)body[0],
            BinaryPrimitives.ReadInt64LittleEndian(body[4..]),
            new DateTimeOffset(
                new DateTime(
                    BinaryPrimitives.ReadInt64LittleEndian(body[12..]),
                    DateTimeKind.Utc)),
            TimeSpan.FromSeconds(
                BitConverter.Int64BitsToDouble(
                    BinaryPrimitives.ReadInt64LittleEndian(body[20..]))),
            BitConverter.Int64BitsToDouble(
                BinaryPrimitives.ReadInt64LittleEndian(body[28..])),
            (MeasurementUnit)body[1],
            double.IsNaN(temperature) ? null : temperature);
    }
}
