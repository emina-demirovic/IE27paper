using System.Diagnostics;
using System.Runtime.InteropServices;

namespace SchedulingV2;

internal sealed record CpuOptions(double Interval, int Window, double Stale, double Grace,
    string Condition, double Phase, int LoadPid, string Gate, int LogicalCpus);

internal sealed record Counters(double Host, double Work, double Generator);
internal sealed record Sample(long Ticks, double? HostBusy, double? WorkloadBusy, double? GeneratorBusy,
    double? External, double? SmoothedExternal, int EffectiveBudget, string? Fallback, long[] BlockedSince);

// One publisher. Each reader gets one immutable snapshot, including the start of
// continuous insufficient capacity for each BLAS limit supported by the manifest.
internal sealed class CpuPolicy(CpuOptions options, int budget, bool adaptive, int logicalCpus)
{
    public int LogicalCpus => logicalCpus;
    private readonly Queue<double> _window = new();
    private Counters? _previous;
    private long _previousTime;
    private Sample _latest = new(0, null, null, null, null, null, budget, "startup", new long[5]);

    public Sample At(long now)
    {
        var s = Volatile.Read(ref _latest);
        return s.Fallback == null && Stopwatch.GetElapsedTime(s.Ticks, now).TotalSeconds > options.Stale
            ? s with { EffectiveBudget = budget, Fallback = "stale" } : s;
    }

    public Sample Observe(long now, Counters? current)
    {
        double? host = null, work = null, generator = null, external = null, smooth = null;
        string? fallback = "unavailable";
        double dt = Stopwatch.GetElapsedTime(_previousTime, now).TotalSeconds;
        var previous = _previous;
        if (current != null && previous != null && dt > 0 && dt <= options.Stale &&
            current.Host >= previous.Host && current.Work >= previous.Work && current.Generator >= previous.Generator)
        {
            host = (current.Host - previous.Host) / dt;
            work = (current.Work - previous.Work) / dt;
            generator = (current.Generator - previous.Generator) / dt;
            external = Math.Clamp(host.Value - work.Value, 0, logicalCpus);
            _window.Enqueue(external.Value);
            if (_window.Count > options.Window) _window.Dequeue();
            if (_window.Count == options.Window) smooth = _window.Average();
            fallback = smooth.HasValue ? null : "warming";
        }
        else
        {
            _window.Clear();
            if (current != null) fallback = previous == null ? "baseline" : "counter_gap";
        }
        int effective = adaptive && smooth.HasValue
            ? Math.Clamp(budget - (int)Math.Round(smooth.Value, MidpointRounding.AwayFromZero), 1, budget)
            : budget;
        var blocked = new long[5];
        for (int p = 1; p < blocked.Length; ++p)
            if (p > effective) blocked[p] = _latest.BlockedSince[p] == 0 ? now : _latest.BlockedSince[p];
        var sample = new Sample(now, host, work, generator, external, smooth, effective, fallback, blocked);
        _previous = current;
        _previousTime = now;
        Volatile.Write(ref _latest, sample);
        return sample;
    }
}

internal sealed class CpuSampler(CpuOptions options, CpuPolicy policy) : IDisposable
{
    [DllImport("v31cpu")]
    private static extern int v31_counters(int loadPid, out double host, out double work, out double load);

    private readonly CancellationTokenSource _stop = new();
    private readonly TaskCompletionSource _warm = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private Task? _loop;
    public List<Sample> History { get; } = new();

    private void Read()
    {
        long start = Stopwatch.GetTimestamp();
        Counters? counters = v31_counters(options.LoadPid, out var h, out var w, out var l) == 0
            ? new(h, w, l) : null;
        long midpoint = start + (Stopwatch.GetTimestamp() - start) / 2;
        var sample = policy.Observe(midpoint, counters);
        History.Add(sample);
        if (sample.SmoothedExternal.HasValue) _warm.TrySetResult();
    }

    public async Task Warmup(CancellationToken token)
    {
        Read();
        _loop = Task.Run(async () =>
        {
            using var timer = new PeriodicTimer(TimeSpan.FromSeconds(options.Interval));
            while (await timer.WaitForNextTickAsync(_stop.Token)) Read();
        });
        var timeout = Task.Delay(TimeSpan.FromSeconds(options.Interval * (options.Window + 2)), token);
        await await Task.WhenAny(_warm.Task, timeout, _loop);
    }

    public void Stop()
    {
        if (_loop == null) return;
        _stop.Cancel();
        try { _loop.GetAwaiter().GetResult(); }
        catch (OperationCanceledException) when (_stop.IsCancellationRequested) { }
        _loop = null;
        Read(); // Include the final partial interval, even for a sub-second batch.
    }

    public void Dispose()
    {
        Stop();
        _stop.Dispose();
    }
}
