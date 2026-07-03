using Coordinator.Services;
using Coordinator.Commands;
using Coordinator.Data;
using Coordinator.Raft;
using Microsoft.Extensions.Options;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

var configuredDatabasePath =
    builder.Configuration[
        "Coordinator:DatabasePath"];

var databasePath =
    string.IsNullOrWhiteSpace(
        configuredDatabasePath)
        ? Path.Combine(
            builder.Environment.ContentRootPath,
            "Data",
            "coordinator.db")
        : Path.GetFullPath(
            configuredDatabasePath,
            builder.Environment.ContentRootPath);

builder.Services.AddDbContextFactory<CoordinatorDbContext>(
    options => options.UseSqlite(
        $"Data Source={databasePath}",
        sqliteOptions => sqliteOptions.MigrationsAssembly(
            typeof(CoordinatorDbContext).Assembly.FullName)));

Directory.CreateDirectory(
    Path.GetDirectoryName(databasePath)!);
        
// Add services to the container.

builder.Services.AddControllers();

// RAFT configuration and services
builder.Services.AddSingleton<
    IValidateOptions<RaftOptions>,
    RaftOptionsValidator>();

builder.Services.AddOptions<RaftOptions>()
    .Bind(
        builder.Configuration.GetSection(
            RaftOptions.SectionName))
    .ValidateOnStart();

builder.Services.AddSingleton<
    IRaftPersistentStateStore,
    SqliteRaftPersistentStateStore>();

builder.Services.AddSingleton<RaftNodeState>();

builder.Services.AddHttpClient(
    "RaftPeer",
    client =>
    {
        client.Timeout =
            TimeSpan.FromSeconds(2);
    });

builder.Services.AddSingleton<
    IRaftPeerClient,
    HttpRaftPeerClient>();

builder.Services.AddSingleton<
    RaftHeartbeatSender>();

builder.Services.AddHostedService<
    RaftHeartbeatBackgroundService>();

builder.Services.AddHostedService<
    RaftElectionBackgroundService>();

builder.Services.AddSingleton<
    RaftElectionService>();

builder.Services.AddSingleton<WorkerRegistry>();
builder.Services.AddSingleton<ExperimentRegistry>();
builder.Services.AddSingleton<CoordinatorCommandProcessor>();
builder.Services.AddHostedService<ExperimentSchedulerService>();
builder.Services.AddHostedService<ExperimentRecoveryService>();

builder.Services.AddOpenApi();

var app = builder.Build();
        
using (var scope = app.Services.CreateScope())
{
    var dbContextFactory = scope.ServiceProvider
        .GetRequiredService<
            IDbContextFactory<CoordinatorDbContext>>();

    await using var dbContext =
        await dbContextFactory.CreateDbContextAsync();

    await dbContext.Database.MigrateAsync();
}

var experimentRegistry =
    app.Services.GetRequiredService<ExperimentRegistry>();

var commandProcessor =
    app.Services.GetRequiredService<
        CoordinatorCommandProcessor>();

var recoveredExperiments =
    experimentRegistry.RequeueInterruptedExperiments();

var interruptedExperiments = 
    experimentRegistry.GetRunning();

var recoveredExperimentCount = 0;

foreach (var experiment in interruptedExperiments)
{
    var command =
        new RecoverExperimentOnStartupCommand(
            CommandId: Guid.NewGuid(),
            OccurredAtUtc: DateTimeOffset.UtcNow,
            ExperimentId: experiment.Id,
            EventId: Guid.NewGuid(),
            PreviousWorkerId:
                experiment.AssignedWorkerId,
            Attempt: experiment.Attempt);

    try
    {
        commandProcessor.Apply(command);
        recoveredExperimentCount++;
    }
    catch (InvalidOperationException)
    {
        app.Logger.LogWarning(
            "Experiment {ExperimentId} could not be " +
            "recovered during Coordinator startup.",
            experiment.Id);
    }
}

if (recoveredExperimentCount > 0)
{
    app.Logger.LogWarning(
        "{ExperimentCount} interrupted experiment(s) " +
        "returned to Pending during Coordinator startup.",
        recoveredExperimentCount);
}

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseHttpsRedirection();

app.UseAuthorization();

app.MapControllers();

app.Run();

public partial class Program
{
    
}