using System.Numerics;
using MathNet.Numerics.IntegralTransforms;

namespace PrecisionLab.Analysis;

public sealed record SpectrumResult(
    double[] Frequency,
    double[] Amplitude,
    double[] AsdFrequency,
    double[] Asd);

public sealed record AllanResult(double[] Tau, double[] Deviation);

public static class SpectrumAnalyzer
{
    public static double EstimateSamplePeriod(IReadOnlyList<double> elapsedSeconds)
    {
        ArgumentNullException.ThrowIfNull(elapsedSeconds);
        double[] differences = elapsedSeconds
            .Zip(elapsedSeconds.Skip(1), (left, right) => right - left)
            .Where(value => double.IsFinite(value) && value > 0)
            .Order()
            .ToArray();
        if (differences.Length == 0)
        {
            return 1;
        }

        int middle = differences.Length / 2;
        return differences.Length % 2 == 0
            ? (differences[middle - 1] + differences[middle]) / 2
            : differences[middle];
    }

    public static SpectrumResult Spectrum(
        IReadOnlyList<double> values,
        double samplePeriodSeconds)
    {
        ArgumentNullException.ThrowIfNull(values);
        double[] y = values.Where(double.IsFinite).ToArray();
        if (y.Length < 4 || samplePeriodSeconds <= 0)
        {
            return new SpectrumResult([], [], [], []);
        }

        double[] detrended = Detrend(y);
        double[] window = Hann(y.Length);
        double coherentGain = window.Average();
        Complex[] transformed = Transform(detrended, window);
        int oneSidedCount = (y.Length / 2) + 1;
        var frequency = new double[oneSidedCount];
        var amplitude = new double[oneSidedCount];
        for (int index = 0; index < oneSidedCount; index++)
        {
            frequency[index] = index / (y.Length * samplePeriodSeconds);
            amplitude[index] =
                transformed[index].Magnitude * 2 / (y.Length * coherentGain);
        }

        amplitude[0] *= 0.5;
        if (y.Length % 2 == 0)
        {
            amplitude[^1] *= 0.5;
        }

        (double[] asdFrequency, double[] asd) =
            Welch(detrended, 1 / samplePeriodSeconds);
        return new SpectrumResult(frequency, amplitude, asdFrequency, asd);
    }

    public static AllanResult AllanDeviation(
        IReadOnlyList<double> values,
        double samplePeriodSeconds,
        bool normalize = false,
        int maximumPoints = 36)
    {
        ArgumentNullException.ThrowIfNull(values);
        double[] y = values.Where(double.IsFinite).ToArray();
        if (y.Length < 4 || samplePeriodSeconds <= 0)
        {
            return new AllanResult([], []);
        }

        if (normalize)
        {
            double mean = y.Average();
            if (mean != 0)
            {
                for (int index = 0; index < y.Length; index++)
                {
                    y[index] /= mean;
                }
            }
        }

        int maximumCluster = Math.Max(1, y.Length / 3);
        int[] clusters = LogSpaceClusters(maximumCluster, maximumPoints);
        var cumulative = new double[y.Length + 1];
        for (int index = 0; index < y.Length; index++)
        {
            cumulative[index + 1] = cumulative[index] + y[index];
        }

        var tau = new List<double>();
        var deviation = new List<double>();
        foreach (int cluster in clusters)
        {
            int averageCount = y.Length - cluster + 1;
            if (averageCount <= cluster)
            {
                continue;
            }

            var averages = new double[averageCount];
            for (int index = 0; index < averageCount; index++)
            {
                averages[index] =
                    (cumulative[index + cluster] - cumulative[index]) / cluster;
            }

            double sum = 0;
            int deltaCount = averages.Length - cluster;
            for (int index = 0; index < deltaCount; index++)
            {
                double delta = averages[index + cluster] - averages[index];
                sum += delta * delta;
            }

            if (deltaCount > 0)
            {
                tau.Add(cluster * samplePeriodSeconds);
                deviation.Add(Math.Sqrt(0.5 * sum / deltaCount));
            }
        }

        return new AllanResult(tau.ToArray(), deviation.ToArray());
    }

    private static (double[] Frequency, double[] Asd) Welch(
        double[] values,
        double sampleFrequency)
    {
        int segmentLength = Math.Min(2_048, values.Length);
        int step = Math.Max(1, segmentLength / 2);
        double[] window = Hann(segmentLength);
        double windowPower = window.Sum(value => value * value);
        int bins = (segmentLength / 2) + 1;
        var psd = new double[bins];
        int segmentCount = 0;
        for (int start = 0; start + segmentLength <= values.Length; start += step)
        {
            double[] segment = values.AsSpan(start, segmentLength).ToArray();
            Complex[] transformed = Transform(segment, window);
            for (int index = 0; index < bins; index++)
            {
                double density =
                    transformed[index].Magnitude * transformed[index].Magnitude /
                    (sampleFrequency * windowPower);
                if (index > 0 && !(segmentLength % 2 == 0 && index == bins - 1))
                {
                    density *= 2;
                }

                psd[index] += density;
            }

            segmentCount++;
        }

        if (segmentCount == 0)
        {
            return ([], []);
        }

        var frequency = new double[bins];
        var asd = new double[bins];
        for (int index = 0; index < bins; index++)
        {
            frequency[index] = index * sampleFrequency / segmentLength;
            asd[index] = Math.Sqrt(Math.Max(0, psd[index] / segmentCount));
        }

        return (frequency, asd);
    }

    private static Complex[] Transform(double[] values, double[] window)
    {
        var buffer = new Complex[values.Length];
        for (int index = 0; index < values.Length; index++)
        {
            buffer[index] = new Complex(values[index] * window[index], 0);
        }

        Fourier.Forward(buffer, FourierOptions.Matlab);
        return buffer;
    }

    private static double[] Detrend(double[] values)
    {
        double xMean = (values.Length - 1) / 2.0;
        double yMean = values.Average();
        double covariance = 0;
        double variance = 0;
        for (int index = 0; index < values.Length; index++)
        {
            double xDelta = index - xMean;
            covariance += xDelta * (values[index] - yMean);
            variance += xDelta * xDelta;
        }

        double slope = variance == 0 ? 0 : covariance / variance;
        var output = new double[values.Length];
        for (int index = 0; index < values.Length; index++)
        {
            output[index] = values[index] - (yMean + slope * (index - xMean));
        }

        return output;
    }

    private static double[] Hann(int count)
    {
        var output = new double[count];
        for (int index = 0; index < count; index++)
        {
            output[index] =
                0.5 - (0.5 * Math.Cos(2 * Math.PI * index / count));
        }

        return output;
    }

    private static int[] LogSpaceClusters(int maximum, int count)
    {
        count = Math.Min(Math.Max(1, count), maximum);
        double maximumLog = Math.Log10(maximum);
        var output = new SortedSet<int>();
        for (int index = 0; index < count; index++)
        {
            double ratio = count == 1 ? 0 : index / (double)(count - 1);
            output.Add(Math.Max(1, (int)Math.Pow(10, maximumLog * ratio)));
        }

        return output.ToArray();
    }
}
