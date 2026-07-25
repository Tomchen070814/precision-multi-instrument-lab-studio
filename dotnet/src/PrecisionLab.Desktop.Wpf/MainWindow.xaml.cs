using System.Windows;
using PrecisionLab.Desktop.Wpf.Charts;
using PrecisionLab.Desktop.Wpf.ViewModels;

namespace PrecisionLab.Desktop.Wpf;

public partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;
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
