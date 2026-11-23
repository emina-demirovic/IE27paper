using Contracts;
using Coordinator.Services;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Logging.Console;
using System.Net;
using System.Net.Http.Json;
using Worker;
using Worker.Execution;

namespace SchedulingV1;

internal sealed class CoordinatorHost(BatchObservation observation, string database)
    : WebApplicationFactory<ExperimentRegistry>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseContentRoot(Path.GetFullPath("../../src/Coordinator"))
            .UseEnvironment("SchedulingV1")
            .UseSetting("Coordinator:DatabasePath", database)
            .UseSetting("Coordinator:SchedulingInterval", Platform.PollInterval)
            .UseSetting("Raft:AutomaticElectionEnabled", "false")
            .UseSetting("Raft:ClientCommandReplicationEnabled", "false")
            .ConfigureLogging(logging =>
            {
                logging.ClearProviders();
                logging.AddSimpleConsole();
                logging.AddFilter<ConsoleLoggerProvider>(null, LogLevel.Error);
            })
            .ConfigureServices(services =>
            {
                services.AddSingleton<IPendingExperimentPolicy>(observation);
                services.Configure<MvcOptions>(options => options.Filters.Add(observation));
            });
    }
}

internal static class Platform
{
    public const string PollInterval = "00:00:00.020";

    private sealed class WorkerHttpClientFactory(HttpClient client) : IHttpClientFactory
    {
        public HttpClient CreateClient(string name) => client;
    }

    public static async Task<double> RunAsync(BatchTask[] order, string scenario, string policy,
        string runId, string directory, int millisecondsPerSecond, bool inProcess, CancellationToken token)
    {
        var tasks = order.ToDictionary(task => task.Id);
        var observation = new BatchObservation(tasks, policy);
        var temporary = Directory.CreateTempSubdirectory("scheduling-v1-");
        try
        {
            await using var host = new CoordinatorHost(observation, Path.Combine(temporary.FullName, "batch.db"));
            if (!inProcess)
                host.UseKestrel(options => options.Listen(IPAddress.Loopback, 0));

            host.StartServer();
            using var client = inProcess ? host.CreateClient() : new HttpClient
            {
                BaseAddress = new Uri(host.Services.GetRequiredService<IServer>()
                    .Features.Get<IServerAddressesFeature>()!.Addresses.Single())
            };
            var workerIds = Enumerable.Range(1, Workload.WorkerCount).Select(i => $"worker-{i:D2}").ToArray();
            var workers = new List<WorkerService>();
            var factory = new WorkerHttpClientFactory(client);
            var executor = new KnownDurationExecutor(tasks, millisecondsPerSecond);
            try
            {
                foreach (var id in workerIds)
                {
                    var configuration = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
                    {
                        ["Worker:Id"] = id,
                        ["Worker:CoordinatorBaseUrl"] = client.BaseAddress!.GetLeftPart(UriPartial.Authority),
                        ["Worker:ExperimentPollingInterval"] = PollInterval
                    }).Build();
                    var worker = new WorkerService(host.Services.GetRequiredService<ILogger<WorkerService>>(),
                        factory, configuration, executor);
                    workers.Add(worker);
                    await worker.StartAsync(token);
                }
                foreach (var task in order)
                {
                    using var response = await client.PostAsJsonAsync("/api/experiments", new CreateExperimentRequest
                    {
                        Name = task.Id, Algorithm = "scheduling-v1-delay", Environment = "local",
                        MaxSteps = 1, Priority = 1, TimeoutSeconds = 120
                    }, token);
                    response.EnsureSuccessStatusCode();
                }

                using (var setup = CancellationTokenSource.CreateLinkedTokenSource(token))
                {
                    setup.CancelAfter(TimeSpan.FromSeconds(30));
                    while (true)
                    {
                        var registered = await client.GetFromJsonAsync<WorkerStatusResponse[]>("/api/workers", setup.Token);
                        if (registered!.Where(w => w.IsOnline).Select(w => w.WorkerId).ToHashSet().SetEquals(workerIds))
                            break;
                        await Task.Delay(20, setup.Token);
                    }
                }

                var batch = await client.GetFromJsonAsync<ExperimentResponse[]>("/api/experiments", token);
                if (batch!.Length != 115 || !tasks.Keys.ToHashSet().SetEquals(batch.Select(t => t.Name)) ||
                    batch.Any(t => t.Status != ExperimentStatus.Pending || t.Priority != 1 || t.Attempt != 0))
                    throw new InvalidOperationException("Expected the entire untouched batch at the release barrier.");

                observation.Release();
                await observation.Finished.WaitAsync(TimeSpan.FromSeconds(90 + 2 * Workload.IdealMakespan(order, policy)
                    * millisecondsPerSecond / 1000.0), token);
            }
            finally
            {
                await Task.WhenAll(workers.Select(worker => worker.StopAsync(CancellationToken.None)));
                foreach (var worker in workers)
                    worker.Dispose();
            }

            return await ValidateAndExport(client, observation, tasks, workerIds, directory, runId,
                scenario, policy, millisecondsPerSecond, token);
        }
        finally
        {
            // Release idle SQLite handles before removing the per-run database.
            using var connection = new SqliteConnection($"Data Source={Path.Combine(temporary.FullName, "batch.db")}");
            SqliteConnection.ClearPool(connection);
            temporary.Delete(recursive: true);
        }
    }

    private static async Task<double> ValidateAndExport(HttpClient client, BatchObservation observation,
        Dictionary<string, BatchTask> tasks, string[] workerIds, string directory, string runId, string scenario,
        string policy, int millisecondsPerSecond, CancellationToken token)
    {
        var batch = (await client.GetFromJsonAsync<ExperimentResponse[]>("/api/experiments", token))!;
        if (batch.Length != tasks.Count || !tasks.Keys.ToHashSet().SetEquals(batch.Select(t => t.Name)))
            throw new InvalidOperationException("Missing or duplicate task in the final batch.");

        var rows = new List<string>();
        var lastCompletion = new Dictionary<string, double>();
        BatchTask? previous = null;
        double latestSlowCompletion = 0;
        foreach (var result in batch.OrderBy(t => observation.Times(t.Id).Dispatch))
        {
            var task = tasks[result.Name];
            var worker = result.AssignedWorkerId;
            var (dispatch, completion) = observation.Times(result.Id);
            if (result.Status != ExperimentStatus.Completed || result.Attempt != 1 ||
                worker is null || !workerIds.Contains(worker) || dispatch < lastCompletion.GetValueOrDefault(worker) ||
                completion <= dispatch || result.ExecutionDurationMs is null ||
                result.ExecutionDurationMs < task.K * millisecondsPerSecond - 2)
                throw new InvalidOperationException($"Invalid execution, duration, or worker overlap for {task.Id}.");

            var events = (await client.GetFromJsonAsync<ExperimentEventResponse[]>(
                $"/api/experiments/{result.Id}/events", token))!;
            if (events.Length != 3 || events.Count(e => e.Type == "Created") != 1 ||
                events.Count(e => e.Type == "Assigned" && e.WorkerId == worker && e.Attempt == 1) != 1 ||
                events.Count(e => e.Type == "Completed" && e.WorkerId == worker && e.Attempt == 1) != 1)
                throw new InvalidOperationException($"Unexpected audit trail for {task.Id}.");

            if (previous is not null)
            {
                bool arrivalOrdered = previous.ArrivalIndex < task.ArrivalIndex;
                bool correct = policy == "FIFO" ? arrivalOrdered :
                    previous.K > task.K || (previous.K == task.K && arrivalOrdered);
                if (!correct)
                    throw new InvalidOperationException($"Dispatch order violated at {previous.Id}, {task.Id}.");
            }

            if (task.K > 1)
                latestSlowCompletion = Math.Max(latestSlowCompletion, completion);
            else if (policy == "LPT" && previous?.K > 1 && dispatch >= latestSlowCompletion)
                throw new InvalidOperationException("Fast work did not overlap the slow tail under LPT.");

            previous = task;
            lastCompletion[worker] = completion;
            rows.Add(Workload.Row($"{runId},{scenario},{policy},{task.Id},{task.ArrivalIndex},{task.K},{worker},{dispatch:R},{completion:R},{result.Id}"));
        }

        if (lastCompletion.Count != Workload.WorkerCount)
            throw new InvalidOperationException("Expected all ten workers to execute tasks.");

        Workload.WriteCsv(Path.Combine(directory, runId + ".csv"),
            "run_id,scenario,policy,task_id,arrival_index,K,worker_id,dispatch_s,completion_s,experiment_id", rows);
        return lastCompletion.Values.Max();
    }
}
