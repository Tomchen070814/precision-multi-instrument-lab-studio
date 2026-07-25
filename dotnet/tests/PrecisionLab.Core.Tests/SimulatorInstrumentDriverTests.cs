using PrecisionLab.Domain;
using PrecisionLab.Drivers.Builtin;

namespace PrecisionLab.Core.Tests;

public sealed class SimulatorInstrumentDriverTests
{
    [Theory]
    [InlineData(MeasurementFunction.DcVoltage, MeasurementUnit.Volt)]
    [InlineData(MeasurementFunction.Resistance4Wire, MeasurementUnit.Ohm)]
    [InlineData(MeasurementFunction.DcCurrent, MeasurementUnit.Ampere)]
    [InlineData(MeasurementFunction.Frequency, MeasurementUnit.Hertz)]
    public async Task SimulatorPreservesFunctionUnits(
        MeasurementFunction function,
        MeasurementUnit expectedUnit)
    {
        var settings = new AcquisitionSettings
        {
            Resource = "SIM::TEST",
            Function = function,
        };
        await using var driver = new SimulatorInstrumentDriver(ChannelId.B, settings);
        await driver.ConnectAsync(CancellationToken.None);
        await driver.ConfigureAsync(settings, CancellationToken.None);

        Measurement reading = await driver.ReadAsync(
            ChannelId.B,
            7,
            TimeSpan.FromSeconds(10),
            includeTemperature: true,
            CancellationToken.None);

        Assert.Equal(ChannelId.B, reading.Channel);
        Assert.Equal(7, reading.Sequence);
        Assert.Equal(expectedUnit, reading.Unit);
        Assert.NotNull(reading.InternalTemperatureC);
        Assert.True(double.IsFinite(reading.Value));
    }
}
