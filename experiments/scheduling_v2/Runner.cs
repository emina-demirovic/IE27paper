using System.Globalization;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using Contracts;
using Coordinator.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Scheduling;
using Worker.Execution;

namespace SchedulingV2;

internal static class Runner
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true
    };

    // Invoked once per run by experiment.py, with the same frozen manifest bytes.
    public static async Task Main(string[] args)
    {
        var (manifestFile, digest, policy, output) = (args[0], args[1], args[2], args[3]);
        int budget = int.Parse(args[4], CultureInfo.InvariantCulture);
        bool inProcess = bool.Parse(args[5]);
        var bytes = File.ReadAllBytes(manifestFile);
        if (Convert.ToHexStringLower(SHA256.HashData(bytes)) != digest)
            throw new InvalidDataException("Manifest content changed after freezing.");
        using var manifest = JsonDocument.Parse(bytes);
        var jobs = manifest.RootElement.GetProperty("jobs").Deserialize<Job[]>(Json)!;
        if (policy is not ("LPT-K" or "LPT-KP") || budget <= 0 || jobs.Length == 0 ||
            jobs.Any(j => string.IsNullOrWhiteSpace(j.TaskId) || j.P is not (1 or 2 or 4) ||
                          j.P > budget || j.N <= 0 || j.R <= 0 || j.Seed < 0 || !double.IsFinite(j.K) || j.K <= 0) ||
            jobs.Select(j => j.TaskId).Distinct().Count() != jobs.Length ||
            !jobs.Select(j => j.ArrivalIndex).SequenceEqual(Enumerable.Range(0, jobs.Length)))
            throw new InvalidDataException("Invalid manifest, arrival indices, policy, or P exceeding B.");

        var clock = new CompletionClock(jobs.Length);
        var admission = new Admission(jobs, budget, policy == "LPT-KP", clock);
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["Worker:Executor:PythonCommand"] = args[6],
            ["Worker:Executor:ScriptPath"] = Path.GetFullPath("matrix_job.py")
        }).Build();
        var requests = jobs.Select(j => new CreateExperimentRequest
        {
            Name = j.TaskId, Algorithm = "numpy-dgemm", Environment = $"{j.N}:{j.P}",
            Seed = j.Seed, MaxSteps = j.R, Priority = 1, TimeoutSeconds = 600
        }).ToArray();
        using var stop = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Cancel(); };
        await LocalBatch.RunAsync(requests, new PythonProcessExperimentExecutor(config), admission, clock,
            inProcess, TimeSpan.FromSeconds(120 + jobs.Sum(j => 4 * j.K + 2)),
            async (client, _, workers) =>
            {
                var batch = (await client.GetFromJsonAsync<ExperimentResponse[]>("/api/experiments", stop.Token))!;
                var events = admission.Events().Select(e => new
                {
                    task_id = e.Task, worker_id = e.Worker, e.Attempt, time_s = clock.Seconds(e.Ticks), e.Delta
                }).ToArray();
                var rows = batch.Select(t => new
                {
                    task_id = t.Name, experiment_id = t.Id, worker_id = t.AssignedWorkerId, t.Attempt,
                    status = t.Status.ToString(), completion_s = clock.Completion(t.Id),
                    process_ms = t.ExecutionDurationMs, t.ResultMessage,
                    metrics = t.MetricsJson == null ? (JsonElement?)null : JsonSerializer.Deserialize<JsonElement>(t.MetricsJson)
                });
                File.WriteAllText(output, JsonSerializer.Serialize(new { manifest_id = digest, policy, budget,
                    workers, events, tasks = rows }, Json));
                return true;
            }, stop.Token, services => services.ConfigureDbContext<CoordinatorDbContext>(
                options => options.AddInterceptors(new ClockInterceptor())), admission.Prepare);
    }
}
