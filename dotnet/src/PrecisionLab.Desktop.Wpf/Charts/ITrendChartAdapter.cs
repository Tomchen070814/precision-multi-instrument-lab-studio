using PrecisionLab.Domain;

namespace PrecisionLab.Desktop.Wpf.Charts;

public interface ITrendChartAdapter : IDisposable
{
    void Append(Measurement measurement);

    void Reset();
}
