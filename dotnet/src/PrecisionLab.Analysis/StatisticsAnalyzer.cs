namespace PrecisionLab.Analysis;

public sealed record StatisticsResult(
    int Count,
    double Mean,
    double Minimum,
    double Maximum,
    double PeakToPeak,
    double StandardDeviation,
    double Rms,
    double Median,
    double NoisePpm,
    double DriftPerHour);

public sealed record LinearFitResult(
    double[] Fitted,
    double DriftPerHour,
    double RSquared);

public static class StatisticsAnalyzer
{
    public static StatisticsResult Describe(
        IReadOnlyList<double> values,
        IReadOnlyList<double>? elapsedSeconds = null)
    {
        ArgumentNullException.ThrowIfNull(values);
        (double[] x, double[] y) = FinitePairs(values, elapsedSeconds);
        if (y.Length == 0)
        {
            return new StatisticsResult(
                0,
                double.NaN,
                double.NaN,
                double.NaN,
                double.NaN,
                double.NaN,
                double.NaN,
                double.NaN,
                double.NaN,
                double.NaN);
        }

        double mean = y.Average();
        double sumSquares = 0;
        double rmsSquares = 0;
        double minimum = double.PositiveInfinity;
        double maximum = double.NegativeInfinity;
        foreach (double value in y)
        {
            double delta = value - mean;
            sumSquares += delta * delta;
            rmsSquares += value * value;
            minimum = Math.Min(minimum, value);
            maximum = Math.Max(maximum, value);
        }

        double standardDeviation =
            y.Length > 1 ? Math.Sqrt(sumSquares / (y.Length - 1)) : 0;
        double drift = Fit(x, y).DriftPerHour;
        double median = Median(y);
        return new StatisticsResult(
            y.Length,
            mean,
            minimum,
            maximum,
            maximum - minimum,
            standardDeviation,
            Math.Sqrt(rmsSquares / y.Length),
            median,
            mean == 0 ? double.NaN : standardDeviation / Math.Abs(mean) * 1e6,
            drift);
    }

    public static LinearFitResult LinearFit(
        IReadOnlyList<double> elapsedSeconds,
        IReadOnlyList<double> values)
    {
        ArgumentNullException.ThrowIfNull(elapsedSeconds);
        ArgumentNullException.ThrowIfNull(values);
        (double[] x, double[] y) = FinitePairs(values, elapsedSeconds);
        return Fit(x, y);
    }

    public static double[] RollingMean(IReadOnlyList<double> values, int window)
    {
        ArgumentNullException.ThrowIfNull(values);
        if (window <= 1 || values.Count == 0)
        {
            return values.ToArray();
        }

        window = Math.Min(window, values.Count);
        var output = Enumerable.Repeat(double.NaN, values.Count).ToArray();
        double sum = 0;
        for (int index = 0; index < values.Count; index++)
        {
            sum += values[index];
            if (index >= window)
            {
                sum -= values[index - window];
            }

            if (index >= window - 1)
            {
                output[index] = sum / window;
            }
        }

        return output;
    }

    public static bool[] SigmaMask(IReadOnlyList<double> values, double threshold)
    {
        ArgumentNullException.ThrowIfNull(values);
        if (values.Count < 2 || threshold <= 0)
        {
            return values.Select(double.IsFinite).ToArray();
        }

        double[] finite = values.Where(double.IsFinite).ToArray();
        if (finite.Length < 2)
        {
            return values.Select(double.IsFinite).ToArray();
        }

        double median = Median(finite);
        double[] deviations = finite.Select(value => Math.Abs(value - median)).ToArray();
        double robustSigma = 1.4826 * Median(deviations);
        if (!double.IsFinite(robustSigma) || robustSigma == 0)
        {
            robustSigma = Describe(finite).StandardDeviation;
        }

        if (!double.IsFinite(robustSigma) || robustSigma == 0)
        {
            return values.Select(double.IsFinite).ToArray();
        }

        return values
            .Select(value =>
                double.IsFinite(value) &&
                Math.Abs(value - median) <= threshold * robustSigma)
            .ToArray();
    }

    internal static (double[] X, double[] Y) FinitePairs(
        IReadOnlyList<double> values,
        IReadOnlyList<double>? elapsedSeconds)
    {
        if (elapsedSeconds is not null && elapsedSeconds.Count != values.Count)
        {
            throw new ArgumentException(
                "Elapsed time and value arrays must have equal length.",
                nameof(elapsedSeconds));
        }

        var x = new List<double>(values.Count);
        var y = new List<double>(values.Count);
        for (int index = 0; index < values.Count; index++)
        {
            double xValue = elapsedSeconds?[index] ?? index;
            double yValue = values[index];
            if (double.IsFinite(xValue) && double.IsFinite(yValue))
            {
                x.Add(xValue);
                y.Add(yValue);
            }
        }

        return (x.ToArray(), y.ToArray());
    }

    private static LinearFitResult Fit(double[] x, double[] y)
    {
        if (y.Length < 2 || x.Max() == x.Min())
        {
            return new LinearFitResult(
                Enumerable.Repeat(double.NaN, y.Length).ToArray(),
                double.NaN,
                double.NaN);
        }

        double xMean = x.Average();
        double yMean = y.Average();
        double covariance = 0;
        double xVariance = 0;
        for (int index = 0; index < y.Length; index++)
        {
            double xDelta = x[index] - xMean;
            covariance += xDelta * (y[index] - yMean);
            xVariance += xDelta * xDelta;
        }

        double slope = covariance / xVariance;
        double intercept = yMean - (slope * xMean);
        var fitted = new double[y.Length];
        double residualSquares = 0;
        double totalSquares = 0;
        for (int index = 0; index < y.Length; index++)
        {
            fitted[index] = (slope * x[index]) + intercept;
            double residual = y[index] - fitted[index];
            residualSquares += residual * residual;
            double centered = y[index] - yMean;
            totalSquares += centered * centered;
        }

        double rSquared =
            totalSquares == 0 ? 1 : 1 - (residualSquares / totalSquares);
        return new LinearFitResult(fitted, slope * 3_600, rSquared);
    }

    private static double Median(IReadOnlyList<double> values)
    {
        double[] sorted = values.Order().ToArray();
        int middle = sorted.Length / 2;
        return sorted.Length % 2 == 0
            ? (sorted[middle - 1] + sorted[middle]) / 2
            : sorted[middle];
    }
}
