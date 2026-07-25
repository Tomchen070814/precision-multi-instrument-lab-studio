namespace PrecisionLab.Analysis;

public static class DisplayDownsampler
{
    public static int[] MinMaxIndices(
        IReadOnlyList<double> x,
        IReadOnlyList<double> y,
        int maximumPoints,
        double? minimumX = null,
        double? maximumX = null)
    {
        ArgumentNullException.ThrowIfNull(x);
        ArgumentNullException.ThrowIfNull(y);
        if (x.Count != y.Count)
        {
            throw new ArgumentException("X and Y arrays must have equal length.", nameof(y));
        }

        if (maximumPoints < 4)
        {
            throw new ArgumentOutOfRangeException(
                nameof(maximumPoints),
                "At least four display points are required.");
        }

        int[] visible = Enumerable.Range(0, x.Count)
            .Where(index =>
                double.IsFinite(x[index]) &&
                double.IsFinite(y[index]) &&
                (!minimumX.HasValue || x[index] >= minimumX.Value) &&
                (!maximumX.HasValue || x[index] <= maximumX.Value))
            .ToArray();
        if (visible.Length <= maximumPoints)
        {
            return visible;
        }

        int bucketCount = Math.Max(1, (maximumPoints - 2) / 2);
        var selected = new SortedSet<int> { visible[0], visible[^1] };
        double bucketWidth = visible.Length / (double)bucketCount;
        for (int bucket = 0; bucket < bucketCount; bucket++)
        {
            int start = Math.Max(1, (int)Math.Floor(bucket * bucketWidth));
            int end = Math.Min(
                visible.Length - 1,
                (int)Math.Floor((bucket + 1) * bucketWidth));
            if (end <= start)
            {
                continue;
            }

            int minimumIndex = visible[start];
            int maximumIndex = visible[start];
            for (int position = start + 1; position < end; position++)
            {
                int index = visible[position];
                if (y[index] < y[minimumIndex])
                {
                    minimumIndex = index;
                }

                if (y[index] > y[maximumIndex])
                {
                    maximumIndex = index;
                }
            }

            selected.Add(minimumIndex);
            selected.Add(maximumIndex);
        }

        return selected.Take(maximumPoints).ToArray();
    }
}
