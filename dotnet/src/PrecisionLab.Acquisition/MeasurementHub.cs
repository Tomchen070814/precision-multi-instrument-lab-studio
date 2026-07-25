using System.Collections.Concurrent;
using System.Threading.Channels;
using PrecisionLab.Domain;

namespace PrecisionLab.Acquisition;

public sealed class MeasurementHub
{
    private readonly ConcurrentDictionary<Guid, Channel<Measurement>> _subscribers = new();

    public MeasurementSubscription Subscribe(int displayCapacity = 512)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(displayCapacity);
        Guid id = Guid.NewGuid();
        Channel<Measurement> channel = Channel.CreateBounded<Measurement>(
            new BoundedChannelOptions(displayCapacity)
            {
                FullMode = BoundedChannelFullMode.DropOldest,
                SingleReader = true,
                SingleWriter = true,
                AllowSynchronousContinuations = false,
            });
        if (!_subscribers.TryAdd(id, channel))
        {
            throw new InvalidOperationException("Unable to register a measurement subscriber.");
        }

        return new MeasurementSubscription(channel.Reader, () => Remove(id));
    }

    public void Publish(Measurement measurement)
    {
        foreach (Channel<Measurement> subscriber in _subscribers.Values)
        {
            subscriber.Writer.TryWrite(measurement);
        }
    }

    public void Complete()
    {
        foreach (Guid id in _subscribers.Keys)
        {
            Remove(id);
        }
    }

    private void Remove(Guid id)
    {
        if (_subscribers.TryRemove(id, out Channel<Measurement>? channel))
        {
            channel.Writer.TryComplete();
        }
    }
}

public sealed class MeasurementSubscription : IDisposable
{
    private Action? _dispose;

    internal MeasurementSubscription(ChannelReader<Measurement> reader, Action dispose)
    {
        Reader = reader;
        _dispose = dispose;
    }

    public ChannelReader<Measurement> Reader { get; }

    public void Dispose() => Interlocked.Exchange(ref _dispose, null)?.Invoke();
}
