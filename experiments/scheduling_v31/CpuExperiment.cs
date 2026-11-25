using System.Collections.Concurrent;
using System.Diagnostics;
using Coordinator.Data;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Scheduling;

namespace SchedulingV2;

internal sealed record Poll(string? Name, string? Fixed, long Seq, string? Fallback);
internal sealed record DispatchInfo(long Seq, int Effective, string? Fallback, bool Solo);
internal sealed record Deferred(long Seq, string Fixed, double TimeS);

internal sealed class CpuExperiment(CpuOptions options, CpuPolicy policy, CompletionClock clock,
    Func<long>? timestamp = null) : IDisposable
{
    public CpuSampler Sampler { get; } = new(options, policy);
    private readonly ConcurrentDictionary<long, Deferred> _deferred = new();
    private readonly ConcurrentDictionary<string, double> _fallbacks = new();

    public void Bind(SqliteConnection connection)
    {
        // EF opens a fresh logical connection for each selection / assignment.
        // Capture on first SQL use (after the writer lock for an assignment).
        // The guard and its audit trigger then see exactly the same decision.
        var decision = new Lazy<(long Now, Sample Sample)>(() =>
        {
            long now = timestamp?.Invoke() ?? Stopwatch.GetTimestamp();
            return (now, policy.At(now));
        });
        connection.CreateFunction("v31_effective", () => decision.Value.Sample.EffectiveBudget);
        connection.CreateFunction("v31_fallback", () => decision.Value.Sample.Fallback);
        connection.CreateFunction("v31_grace_elapsed", (int p, long lastChange) =>
        {
            var (now, s) = decision.Value;
            var since = Math.Max(Math.Max(clock.StartTicks, lastChange), s.BlockedSince[p]);
            return Stopwatch.GetElapsedTime(since, now).TotalSeconds >= options.Grace;
        });
    }

    public void Prepare(CoordinatorDbContext db) =>
        db.Database.ExecuteSqlRaw(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "adaptive.sql")));

    public string? Select(CoordinatorDbContext db)
    {
        var poll = db.Database.SqlQueryRaw<Poll>("SELECT * FROM v31_poll").AsEnumerable().Single();
        double elapsed = clock.Seconds(Stopwatch.GetTimestamp());
        if (poll.Name == null && poll.Fixed != null)
            _deferred.TryAdd(poll.Seq, new(poll.Seq, poll.Fixed, elapsed));
        if (poll.Fallback != null) _fallbacks.TryAdd(poll.Fallback, elapsed);
        return poll.Name;
    }

    public void Release()
    {
        // Python time.monotonic() and Stopwatch use uptime on this Mac.
        File.WriteAllText(options.Gate + ".tmp",
            ((double)clock.StartTicks / Stopwatch.Frequency).ToString("R", System.Globalization.CultureInfo.InvariantCulture));
        File.Move(options.Gate + ".tmp", options.Gate);
    }

    public object Report(IServiceProvider services)
    {
        using var db = services.GetRequiredService<IDbContextFactory<CoordinatorDbContext>>().CreateDbContext();
        return new
        {
            options, logical_cpus = policy.LogicalCpus,
            samples = Sampler.History.Select(s => new { elapsed_s = clock.Seconds(s.Ticks), s.HostBusy,
                s.WorkloadBusy, s.GeneratorBusy, s.External, s.SmoothedExternal, s.EffectiveBudget, s.Fallback }),
            dispatch = db.Database.SqlQueryRaw<DispatchInfo>("SELECT * FROM v31_dispatch ORDER BY seq").ToList(),
            deferred = _deferred.Values.OrderBy(d => d.Seq), fallback_polls = _fallbacks
        };
    }

    public void Dispose() => Sampler.Dispose();
}
