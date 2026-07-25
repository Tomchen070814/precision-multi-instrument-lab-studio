using PrecisionLab.Domain;
using PrecisionLab.Drivers.Builtin;

namespace PrecisionLab.Core.Tests;

public sealed class DriverCatalogTests
{
    [Fact]
    public void Catalog_ContainsExactlyFourteenModels()
    {
        Assert.Equal(14, InstrumentCatalog.All.Count);
        Assert.Equal(
            Enum.GetValues<InstrumentModel>().Order(),
            InstrumentCatalog.All.Select(item => item.Model).Order());
    }

    [Fact]
    public void Factory_FailsClosedForLiveResource()
    {
        var factory = new DigitalTwinDriverFactory();
        var settings = new AcquisitionSettings
        {
            InstrumentModel = InstrumentModel.Keysight3458A,
            Resource = "GPIB0::22::INSTR",
        };

        NotSupportedException exception = Assert.Throws<NotSupportedException>(
            () => factory.Create(ChannelId.A, settings));
        Assert.Contains("disabled", exception.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task DigitalTwin_EmitsRequestedIdentityAndSequence()
    {
        var factory = new DigitalTwinDriverFactory();
        var settings = new AcquisitionSettings
        {
            InstrumentModel = InstrumentModel.Fluke8508A,
            Resource = "SIM::8508A",
            Function = MeasurementFunction.Resistance4Wire,
        };
        await using var driver = factory.Create(ChannelId.B, settings);

        InstrumentIdentity identity = await driver.ConnectAsync(CancellationToken.None);
        await driver.ConfigureAsync(settings, CancellationToken.None);
        Measurement measurement = await driver.ReadAsync(
            ChannelId.B,
            7,
            TimeSpan.FromSeconds(2),
            includeTemperature: true,
            CancellationToken.None);

        Assert.Equal(InstrumentModel.Fluke8508A, identity.Model);
        Assert.Equal(InstrumentProtocol.DigitalTwin, identity.Protocol);
        Assert.Equal(7, measurement.Sequence);
        Assert.Equal(MeasurementUnit.Ohm, measurement.Unit);
    }
}
