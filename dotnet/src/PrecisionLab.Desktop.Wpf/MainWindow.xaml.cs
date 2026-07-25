using System.Diagnostics.CodeAnalysis;
using System.Windows;
using PrecisionLab.Desktop.Wpf.Charts;
using PrecisionLab.Desktop.Wpf.ViewModels;

namespace PrecisionLab.Desktop.Wpf;

[SuppressMessage(
    "Design",
    "CA1001",
    Justification = "WPF owns the window lifetime; Closed disposes the chart adapter.")]
public partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;
    [SuppressMessage(
        "Performance",
        "CA1859",
        Justification = "The interface is the intentional chart-library isolation boundary.")]
    private readonly ITrendChartAdapter _trendChart;

    public MainWindow(MainViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
        _trendChart = new ScottPlotTrendChartAdapter(TrendPlot);
        _viewModel.MeasurementArrived += _trendChart.Append;
        Closed += OnClosed;
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        _viewModel.MeasurementArrived -= _trendChart.Append;
        _trendChart.Dispose();
    }
}
