using PrecisionLab.Analysis;

namespace PrecisionLab.Core.Tests;

public sealed class AnalysisGoldenTests
{
    [Fact]
    public void StatisticsMatchPythonNumpyGoldenVector()
    {
        double[] elapsed = [0, 1, 2, 3];
        double[] values = [1, 2, 3, 4];

        StatisticsResult result = StatisticsAnalyzer.Describe(values, elapsed);
        LinearFitResult trend = StatisticsAnalyzer.LinearFit(elapsed, values);

        Assert.Equal(2.5, result.Mean, 12);
        Assert.Equal(1.2909944487358056, result.StandardDeviation, 12);
        Assert.Equal(2.7386127875258306, result.Rms, 12);
        Assert.Equal(2.5, result.Median, 12);
        Assert.Equal(3_600, result.DriftPerHour, 10);
        Assert.Equal(1, trend.RSquared, 12);
    }

    [Fact]
    public void SpectrumFindsKnownFiveHertzTone()
    {
        const int count = 1_000;
        const double samplePeriod = 0.001;
        double[] values = Enumerable.Range(0, count)
            .Select(index => Math.Sin(2 * Math.PI * 5 * index * samplePeriod))
            .ToArray();

        SpectrumResult result = SpectrumAnalyzer.Spectrum(values, samplePeriod);
        int peak = Enumerable.Range(1, result.Amplitude.Length - 1)
            .OrderByDescending(index => result.Amplitude[index])
            .First();

        Assert.Equal(5, result.Frequency[peak], 10);
        Assert.InRange(result.Amplitude[peak], 0.99, 1.01);
        Assert.All(result.Asd, value => Assert.True(double.IsFinite(value) && value >= 0));
    }

    [Fact]
    public void AllanDeviationOfConstantSignalIsZero()
    {
        double[] values = Enumerable.Repeat(10.0, 1_024).ToArray();

        AllanResult result = SpectrumAnalyzer.AllanDeviation(values, 0.1);

        Assert.NotEmpty(result.Tau);
        Assert.All(result.Deviation, value => Assert.Equal(0, value, 12));
    }

    [Fact]
    public void EnvelopeDownsamplingPreservesNarrowSpike()
    {
        double[] values = new double[10_000];
        values[4_321] = 100;
        double[] elapsed = Enumerable.Range(0, values.Length)
            .Select(index => (double)index)
            .ToArray();

        int[] selected = DisplayDownsampler.MinMaxIndices(elapsed, values, 200);

        Assert.Contains(4_321, selected);
        Assert.InRange(selected.Length, 2, 200);
    }
}
