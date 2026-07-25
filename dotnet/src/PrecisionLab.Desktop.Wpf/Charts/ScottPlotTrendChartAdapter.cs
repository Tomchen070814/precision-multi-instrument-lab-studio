using System.Windows.Threading;
using PrecisionLab.Domain;
using ScottPlot.WPF;

namespace PrecisionLab.Desktop.Wpf.Charts;

public sealed class ScottPlotTrendChartAdapter : ITrendChartAdapter
{
    private const int DisplayPointLimit = 20_000;
    private readonly WpfPlot _plot;
    private readonly DispatcherTimer _renderTimer;
    private readonly Dictionary<ChannelId, Queue<Measurement>> _points =
        Enum.GetValues<ChannelId>().ToDictionary(
            channel => channel,
            _ => new Queue<Measurement>());
    private bool _dirty;

    public ScottPlotTrendChartAdapter(WpfPlot plot)
    {
        _plot = plot;
        _plot.Plot.Title("Multi-channel trend");
        _plot.Plot.XLabel("Elapsed time (s)");
        _plot.Plot.YLabel("Value");
        _renderTimer = new DispatcherTimer(
            TimeSpan.FromMilliseconds(100),
            DispatcherPriority.Background,
            (_, _) => Render(),
            _plot.Dispatcher);
        _renderTimer.Start();
    }

    public void Append(Measurement measurement)
    {
        Queue<Measurement> channel = _points[measurement.Channel];
        channel.Enqueue(measurement);
        while (channel.Count > DisplayPointLimit)
        {
            channel.Dequeue();
        }

        _dirty = true;
    }

    public void Reset()
    {
        foreach (Queue<Measurement> channel in _points.Values)
        {
            channel.Clear();
        }

        _dirty = true;
    }

    public void Dispose() => _renderTimer.Stop();

    private void Render()
    {
        if (!_dirty)
        {
            return;
        }

        _plot.Plot.Clear();
        foreach ((ChannelId channel, Queue<Measurement> values) in _points)
        {
            if (values.Count == 0)
            {
                continue;
            }

            Measurement[] snapshot = values.ToArray();
            double[] x = snapshot.Select(item => item.Elapsed.TotalSeconds).ToArray();
            double[] y = snapshot.Select(item => item.Value).ToArray();
            var series = _plot.Plot.Add.Scatter(x, y);
            series.LegendText = $"Channel {channel} · {snapshot[^1].Unit.Symbol()}";
        }

        _plot.Plot.ShowLegend();
        _plot.Refresh();
        _dirty = false;
    }
}
