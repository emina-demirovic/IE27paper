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

internal record Job(string TaskId, int ArrivalIndex, int N, int R, int Seed, int P, double K);
internal record Reservation(string Task, string Worker, int Attempt, long Ticks, int Delta);

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

internal sealed class Admission(Job[] jobs, int budget, bool constrained, CompletionClock clock, CpuExperiment? cpu = null)
    : IPendingExperimentPolicy
{
    private IDbContextFactory<CoordinatorDbContext> _factory = null!;

    public void Prepare(IServiceProvider services)
    {
        _factory = services.GetRequiredService<IDbContextFactory<CoordinatorDbContext>>();
        using var db = _factory.CreateDbContext();
        using var tx = db.Database.BeginTransaction();
        db.Database.ExecuteSqlRaw(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "admission.sql")));
        db.Database.ExecuteSql($"INSERT INTO v2_config VALUES ({budget},{constrained})");
        foreach (var j in jobs)
            db.Database.ExecuteSql($"INSERT INTO v2_tasks VALUES ({j.TaskId},{j.ArrivalIndex},{j.K},{j.P})");
        cpu?.Prepare(db);
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
            "SELECT task AS Task, worker AS Worker, attempt AS Attempt, ticks AS Ticks, delta AS Delta FROM v2_events ORDER BY seq")
            .ToList();
    }
}
