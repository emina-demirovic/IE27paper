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

namespace Scheduling;

internal sealed class CoordinatorHost(IPendingExperimentPolicy policy, CompletionClock clock, string database,
    Action<IServiceCollection>? configure)
    : WebApplicationFactory<ExperimentRegistry>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseContentRoot(Path.GetFullPath("../../src/Coordinator"))
            .UseEnvironment("SchedulingV1")
            .UseSetting("Coordinator:DatabasePath", database)
            .UseSetting("Coordinator:SchedulingInterval", LocalBatch.PollInterval)
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
                services.AddSingleton(policy);
                services.Configure<MvcOptions>(options => options.Filters.Add(clock));
                configure?.Invoke(services);
            });
    }
}

internal static class LocalBatch
{
    public const string PollInterval = "00:00:00.020";

    private sealed class WorkerHttpClientFactory(HttpClient client) : IHttpClientFactory
    {
        public HttpClient CreateClient(string name) => client;
    }

    public const int WorkerCount = 10;

    public static async Task<T> RunAsync<T>(CreateExperimentRequest[] requests, IExperimentExecutor executor,
        IPendingExperimentPolicy policy, CompletionClock clock, bool inProcess, TimeSpan deadline,
        Func<HttpClient, IServiceProvider, string[], Task<T>> export, CancellationToken token,
        Action<IServiceCollection>? configure = null, Action<IServiceProvider>? prepare = null,
        Func<CancellationToken, Task>? warmup = null, Action? released = null, Action? finished = null)
    {
        var temporary = Directory.CreateTempSubdirectory("scheduling-");
        try
        {
            await using var host = new CoordinatorHost(policy, clock, Path.Combine(temporary.FullName, "batch.db"), configure);
            if (!inProcess)
                host.UseKestrel(options => options.Listen(IPAddress.Loopback, 0));

            host.StartServer();
            using var client = inProcess ? host.CreateClient() : new HttpClient
            {
                BaseAddress = new Uri(host.Services.GetRequiredService<IServer>()
                    .Features.Get<IServerAddressesFeature>()!.Addresses.Single())
            };
            prepare?.Invoke(host.Services);
            var workerIds = Enumerable.Range(1, WorkerCount).Select(i => $"worker-{i:D2}").ToArray();
            var workers = new List<WorkerService>();
            var factory = new WorkerHttpClientFactory(client);
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
                foreach (var request in requests)
                {
                    using var response = await client.PostAsJsonAsync("/api/experiments", request, token);
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
                if (batch!.Length != requests.Length ||
                    !requests.Select(t => t.Name).ToHashSet().SetEquals(batch.Select(t => t.Name)) ||
                    batch.Any(t => t.Status != ExperimentStatus.Pending || t.Priority != 1 || t.Attempt != 0))
                    throw new InvalidOperationException("Expected the entire untouched batch at the release barrier.");

                if (warmup != null) await warmup(token);
                clock.Release();
                released?.Invoke();
                await clock.Finished.WaitAsync(deadline, token);
                finished?.Invoke();
            }
            finally
            {
                await Task.WhenAll(workers.Select(worker => worker.StopAsync(CancellationToken.None)));
                foreach (var worker in workers)
                    worker.Dispose();
            }

            return await export(client, host.Services, workerIds);
        }
        finally
        {
            // Release idle SQLite handles before removing the per-run database.
            using var connection = new SqliteConnection($"Data Source={Path.Combine(temporary.FullName, "batch.db")}");
            SqliteConnection.ClearPool(connection);
            temporary.Delete(recursive: true);
        }
    }

}
