using System.Data.Common;
using System.Diagnostics;
using Coordinator.Data;
using Coordinator.Services;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Scheduling;

namespace SchedulingV2;

internal record Job(string TaskId, int ArrivalIndex, string Algorithm, string Environment, int MaxSteps, int Seed, int P, double K, string? Group = null);
internal record Reservation(string Task, string Worker, int Attempt, long Ticks, int Delta, string Utc);

internal sealed class ClockInterceptor(CpuExperiment? cpu = null) : DbConnectionInterceptor
{
    private void Install(DbConnection connection)
    {
        ((SqliteConnection)connection).CreateFunction("v2_ticks", Stopwatch.GetTimestamp);
        cpu?.Bind((SqliteConnection)connection);
    }

    public override void ConnectionOpened(DbConnection connection, ConnectionEndEventData eventData) =>
        Install(connection);

    public override Task ConnectionOpenedAsync(DbConnection connection, ConnectionEndEventData eventData,
        CancellationToken cancellationToken = default)
    {
        Install(connection);
        return Task.CompletedTask;
    }
}

internal sealed class Admission(Job[] jobs, int budget, string policy, CompletionClock clock, CpuExperiment? cpu = null, int? matrixCap = null, bool noWaitAt99 = false)
    : IPendingExperimentPolicy
{
    public int MatrixPriorityBonusMs => policy == "CpuBandsBlock20Matrix" ? 3000 : 0;

    private IDbContextFactory<CoordinatorDbContext> _factory = null!;

    public void Prepare(IServiceProvider services)
    {
        _factory = services.GetRequiredService<IDbContextFactory<CoordinatorDbContext>>();
        using var db = _factory.CreateDbContext();
        using var tx = db.Database.BeginTransaction();
        db.Database.ExecuteSqlRaw(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "admission.sql")));
        db.Database.ExecuteSql($"INSERT INTO v2_config VALUES ({budget},1,{matrixCap})");
        foreach (var j in jobs)
        {
            bool longMatrix = j.Algorithm == "numeric-matmul" &&
                (j.Environment, j.MaxSteps) is ("matrix-1536", 945) or ("matrix-1600", 900);
            double priorityK = policy == "FIFO" ? 0 : j.K;
            if (longMatrix) priorityK += MatrixPriorityBonusMs;
            db.Database.ExecuteSql($"INSERT INTO v2_tasks VALUES ({j.TaskId},{j.ArrivalIndex},{priorityK},{j.P})");
        }
        cpu?.Prepare(db);
        if (policy is "CpuBands" or "CpuBandsBlock10" or "CpuBandsBlock20Matrix")
        {
            db.Database.ExecuteSqlRaw(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "cpu_bands.sql")));
            db.Database.ExecuteSql($"INSERT INTO band_settings VALUES ({noWaitAt99})");
            foreach (var job in jobs)
            {
                int fifoBlock = policy switch
                {
                    "CpuBandsBlock10" => job.ArrivalIndex / 10,
                    "CpuBandsBlock20Matrix" => job.ArrivalIndex / 20,
                    _ => 0
                };
                db.Database.ExecuteSql($"INSERT INTO band_tasks VALUES ({job.TaskId},{job.Group},{fifoBlock})");
            }
        }
        if (policy == "FamilyFIFO")
        {
            db.Database.ExecuteSqlRaw(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "family_fifo.sql")));
            var longConfigs = jobs.Where(j => j.Algorithm == "numeric-matmul")
                .OrderByDescending(j => j.K).ThenBy(j => j.ArrivalIndex)
                .Select(j => (j.Environment, j.MaxSteps)).Distinct().Take(2).ToHashSet();
            foreach (var job in jobs)
            {
                var isLong = job.Algorithm == "numeric-matmul" && longConfigs.Contains((job.Environment, job.MaxSteps));
                db.Database.ExecuteSql($"INSERT INTO family_tasks VALUES ({job.TaskId},{job.ArrivalIndex},{job.Algorithm},{isLong})");
            }
        }
        tx.Commit();
    }

    public ExperimentEntity? SelectNext(IEnumerable<ExperimentEntity> pending)
    {
        if (!clock.Released)
            return null;
        using var db = _factory.CreateDbContext();
        var name = cpu != null ? cpu.Select(db) : db.Database
            .SqlQueryRaw<string>("SELECT name AS Value FROM v2_next").AsEnumerable().SingleOrDefault();
        return name == null ? null : pending.FirstOrDefault(e => e.Name == name);
    }

    public List<Reservation> Events()
    {
        using var db = _factory.CreateDbContext();
        return db.Database.SqlQueryRaw<Reservation>(
            "SELECT task AS Task, worker AS Worker, attempt AS Attempt, ticks AS Ticks, delta AS Delta, utc AS Utc FROM v2_events ORDER BY seq")
            .ToList();
    }
}
