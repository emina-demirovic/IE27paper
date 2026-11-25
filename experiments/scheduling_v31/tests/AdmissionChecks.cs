using System.Diagnostics;
using Microsoft.Data.Sqlite;
using Scheduling;
using SchedulingV2;

internal sealed class Fixture : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("v31-check-").FullName;
    private readonly CompletionClock _clock = new(1);
    private readonly CpuPolicy _policy;
    private readonly CpuExperiment _cpu;
    private long _now;
    private double _host, _work;
    public Fixture((int K, int P)[] jobs, bool adaptive = true, int window = 1)
    {
        _clock.Release();
        _now = _clock.StartTicks;
        var options = new CpuOptions(1, window, 3, 2, "quiet", 10, 0, "", 10);
        _policy = new(options, 10, adaptive, 10);
        _cpu = new(options, _policy, _clock, () => _now);
        Sql("CREATE TABLE Experiments(Id TEXT PRIMARY KEY, Name TEXT, Status INTEGER DEFAULT 0, " +
            "AssignedWorkerId TEXT, Attempt INTEGER DEFAULT 0)");
        foreach (var file in new[] { "admission.sql", "adaptive.sql" })
            Sql(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, file)));
        Sql("INSERT INTO v2_config VALUES(10,1)");
        for (int i = 0; i < jobs.Length; i++)
            Sql($"INSERT INTO v2_tasks VALUES('{i}',{i},{jobs[i].K},{jobs[i].P});" +
                $"INSERT INTO Experiments(Id,Name) VALUES('{i}','{i}')");
        _policy.Observe(_now, new(0, 0, 0));
    }

    private SqliteConnection Open()
    {
        var db = new SqliteConnection($"Data Source={_dir}/batch.db;Pooling=false");
        db.Open();
        _cpu.Bind(db);
        db.CreateFunction("v2_ticks", () => _now);
        return db;
    }

    public void Advance(double seconds) => _now += (long)(seconds * Stopwatch.Frequency);

    public Sample Sample(double host, double work)
    {
        Advance(1);
        _host += host;
        _work += work;
        return _policy.Observe(_now, new(_host, _work, 0));
    }

    public Sample Missing()
    {
        Advance(1);
        return _policy.Observe(_now, null);
    }

    public string? Value(string sql)
    {
        using var db = Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = sql;
        return cmd.ExecuteScalar()?.ToString();
    }

    public int Sql(string sql)
    {
        using var db = Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = sql;
        return cmd.ExecuteNonQuery();
    }

    public string? Next() => Value("SELECT Name FROM v2_next");
    public int Assign(int id, int worker) => Sql($"UPDATE Experiments SET Status=1, " +
        $"AssignedWorkerId='{worker}',Attempt=Attempt+1 WHERE Id='{id}' AND Status=0");
    public void End(int id) => Sql($"UPDATE Experiments SET Status=2 WHERE Id='{id}' AND Status=1");
    public void Dispose()
    {
        _cpu.Dispose();
        Directory.Delete(_dir, true);
    }
}

internal static class AdmissionChecks
{
    private static void Equal<T>(T expected, T actual)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new Exception($"Expected [{expected}], observed [{actual}]");
    }

    static void ZeroReplaysFixed()
    {
        (int, int)[] jobs = [(2,4), (2,4), (4,2), (1,1), (3,4)];
        using var fixedRun = new Fixture(jobs, false);
        using var adaptive = new Fixture(jobs);
        fixedRun.Sample(9, 9);
        Equal(10, adaptive.Sample(9, 9).EffectiveBudget);
        foreach (int i in new[] { 2, 4, 0, 1, 3 })
        {
            Equal(i.ToString(), fixedRun.Next());
            Equal(fixedRun.Next(), adaptive.Next());
            Equal(1, fixedRun.Assign(i, 0));
            Equal(1, adaptive.Assign(i, 0));
            fixedRun.End(i);
            adaptive.End(i);
        }
    }

    static void AdmissionAndWake()
    {
        using var f = new Fixture([(9,4), (8,2), (7,4), (6,1)]);
        f.Sample(5, 5);
        Equal(1, f.Assign(0, 0));
        Equal(1, f.Assign(1, 1));
        Equal(7, f.Sample(9, 6).EffectiveBudget);
        Equal("3", f.Next());
        Equal(0, f.Assign(2, 2));
        Equal(1, f.Assign(3, 2));
        Equal(2, f.Sample(9, 1).EffectiveBudget);
        Equal("7", f.Value("SELECT reserved FROM v2_load"));
        Equal(null, f.Next());
        f.End(3);
        Equal(null, f.Next());
        f.Sample(5, 5);
        Equal("2", f.Next()); // idle scheduler poll, no intervening completion
    }

    static void GraceAndStale()
    {
        using var f = new Fixture([(2,4), (1,4)]);
        f.Sample(9, 0);
        Equal(null, f.Next());
        f.Advance(1.99);
        Equal(null, f.Next());
        f.Advance(.02);
        Equal("0", f.Next());
        Equal(1, f.Assign(0, 0));
        Equal("1", f.Value("SELECT solo FROM v31_dispatch"));
        f.Advance(2);
        Equal("stale", f.Value("SELECT v31_fallback()"));
        Equal("10", f.Value("SELECT v31_effective()"));
        Equal(null, f.Next()); // override stays alone through recovery
        f.End(0);
        Equal("1", f.Next());
        Equal(1, f.Assign(1, 0));
        Equal("stale", f.Value("SELECT fallback FROM v31_dispatch ORDER BY seq DESC LIMIT 1"));
    }

    static void UnavailableAndFixedBudget()
    {
        using var fixedRun = new Fixture([(1,4)], false);
        Equal(10, fixedRun.Sample(9, 0).EffectiveBudget);
        using var f = new Fixture([(1,4)]);
        Equal(1, f.Sample(9, 0).EffectiveBudget);
        Equal(null, f.Next());
        Equal("unavailable", f.Missing().Fallback);
        Equal("0", f.Next());
        Equal("baseline", f.Sample(9, 0).Fallback);
        Equal(1, f.Sample(9, 0).EffectiveBudget);
        Equal(null, f.Next()); // fresh grace period after recovery
    }

    static void WindowAndRounding()
    {
        using var f = new Fixture([(1,1)], window: 3);
        Equal("warming", f.Sample(3, 5).Fallback); // clamp below zero
        Equal("warming", f.Sample(1.5, 0).Fallback);
        Equal(8, f.Sample(4, 1).EffectiveBudget); // mean 1.5 rounds up
        Equal(10d, f.Sample(16, 0).External); // clamp above logical CPU count
    }

    static void ConcurrentRequests()
    {
        using var f = new Fixture([(5,4), (4,4), (3,1), (2,1), (1,1)]);
        f.Sample(4, 0);
        Equal(1, f.Assign(0, 0)); // two units left
        using var barrier = new Barrier(5);
        var requests = Enumerable.Range(1, 5).Select(w => Task.Run(() =>
        {
            Equal("2", f.Next());
            Equal(true, barrier.SignalAndWait(TimeSpan.FromSeconds(10)));
            int? candidate = 2;
            while (candidate.HasValue)
            {
                if (f.Assign(candidate.Value, w) == 1) return 1;
                candidate = f.Next() is string next ? int.Parse(next) : null;
            }
            return 0;
        })).ToArray();
        Equal(2, Task.WhenAll(requests).GetAwaiter().GetResult().Sum());
        Equal("6", f.Value("SELECT reserved FROM v2_load"));
    }

    public static void Main()
    {
        foreach (Action test in new Action[] { ZeroReplaysFixed, AdmissionAndWake, GraceAndStale,
                                               UnavailableAndFixedBudget, WindowAndRounding, ConcurrentRequests })
        {
            test();
            Console.WriteLine($"PASS {test.Method.Name}");
        }
    }
}
