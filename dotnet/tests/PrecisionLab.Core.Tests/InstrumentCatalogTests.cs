using PrecisionLab.Domain;

namespace PrecisionLab.Core.Tests;

public sealed class InstrumentCatalogTests
{
    [Fact]
    public void Catalog_preserves_all_fourteen_v052_models()
    {
        Assert.Equal(14, InstrumentCatalog.All.Count);
        Assert.Equal(14, InstrumentCatalog.All.Select(item => item.Model).Distinct().Count());
    }

    [Fact]
    public void Legacy_protocols_are_not_misclassified_as_scpi()
    {
        Assert.Equal(
            InstrumentProtocol.HpIb3458A,
            InstrumentCatalog.Get(InstrumentModel.Keysight3458A).Protocol);
        Assert.Equal(
            InstrumentProtocol.Ieee488Fluke8508A,
            InstrumentCatalog.Get(InstrumentModel.Fluke8508A).Protocol);
        Assert.Equal(
            12,
            InstrumentCatalog.All.Count(item => item.Protocol == InstrumentProtocol.Scpi));
    }
}
