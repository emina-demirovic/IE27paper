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
    public static async Task Main(string[] args)
    {
        var (manifest, policy, output, python) = (args[0], args[1], args[2], args[3]);
        int budget = int.Parse(args[4]);
        bool plainFifo = policy == "FIFO" && args.Length == 7 && args[6] == "--no-cpu-sampling";
        bool noWaitAt99 = policy == "CpuBandsBlock20Matrix" && args.Length == 7 && args[6] == "--no-wait-99";
        int? matrixCap = args.Length > 6 && !plainFifo && !noWaitAt99 ? int.Parse(args[6]) : null;
        bool hostBands = policy is "CpuBands" or "CpuBandsBlock10" or "CpuBandsBlock20Matrix";
        byte[] bytes = File.ReadAllBytes(manifest);
        var jobs = JsonSerializer.Deserialize<Job[]>(bytes)!;
        if ((!hostBands && policy is not ("FIFO" or "V31" or "FamilyFIFO")) || budget < 1 || matrixCap is <= 0 || (matrixCap.HasValue && policy != "V31") || jobs.Length == 0 ||
            jobs.Any(j => j.P != 1 || !double.IsFinite(j.K) || j.K <= 0) ||
            (hostBands && jobs.Any(j => j.Group is not ("short" or "medium" or "long"))) ||
            !jobs.Select(j => j.ArrivalIndex).SequenceEqual(Enumerable.Range(0, jobs.Length)))
            throw new InvalidDataException("Invalid policy, budget or manifest.");
        var clock = new CompletionClock(jobs.Length);
        int logicalCpus = int.Parse(args[5]);
        var options = hostBands
            ? new CpuOptions(0.05, 4, 0.25, 2, "quiet", 10, 0, "", logicalCpus, HostOnly: true)
            : new CpuOptions(1, 3, 3, 2, "quiet", 10, 0, "", logicalCpus);
        using var cpu = plainFifo ? null : new CpuExperiment(options, new CpuPolicy(options, budget, policy == "V31",
            options.LogicalCpus), clock, hostBands: hostBands);
        var admission = new Admission(jobs, budget, policy, clock, cpu, matrixCap, noWaitAt99);
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string,string?> {
            ["Worker:Executor:PythonCommand"] = python,
            ["Worker:Executor:ScriptPath"] = Path.GetFullPath("../../src/Worker/Scripts/run_experiment.py")
        }).Build();
        var requests = jobs.Select(j => new CreateExperimentRequest {
            Name=j.TaskId, Algorithm=j.Algorithm, Environment=j.Environment, Seed=j.Seed,
            MaxSteps=j.MaxSteps, Priority=1, TimeoutSeconds=480
        }).ToArray();
        await LocalBatch.RunAsync(requests, new PythonProcessExperimentExecutor(config), admission, clock, true,
            TimeSpan.FromMinutes(30), async (client, services, workers) => {
                var batch = (await client.GetFromJsonAsync<ExperimentResponse[]>("/api/experiments"))!;
                if (batch.Any(t => t.Status != ExperimentStatus.Completed || t.Attempt != 1 ||
                    t.ExecutionDurationMs is null or <= 0 || string.IsNullOrEmpty(t.MetricsJson)))
                    throw new InvalidDataException("Missing successful first-attempt timings or metrics.");
                var rows = batch.Select(t => new { t.Name, t.ExecutionDurationMs, completion = clock.Completion(t.Id),
                    metrics = JsonSerializer.Deserialize<JsonElement>(t.MetricsJson!) });
                var events = admission.Events();
                var data = new { runId=System.Environment.GetEnvironmentVariable("IE27_RUN_ID"), policy, budget, matrixCap, manifestHash=Convert.ToHexStringLower(SHA256.HashData(bytes)),
                    startTicks=clock.StartTicks, ticksPerSecond=System.Diagnostics.Stopwatch.Frequency,
                    noWaitAt99, matrixPriorityBonusMs=admission.MatrixPriorityBonusMs, workers, rows, events, cpu=cpu?.Report(services) };
                File.WriteAllText(output, JsonSerializer.Serialize(data));
                return true;
            }, CancellationToken.None, services => services.ConfigureDbContext<CoordinatorDbContext>(
                db => db.AddInterceptors(new ClockInterceptor(cpu))), admission.Prepare, cpu == null ? null : cpu.Sampler.Warmup,
            finished: cpu == null ? null : cpu.Sampler.Stop,
            databasePath: System.Environment.GetEnvironmentVariable("IE27_ATTEMPT_DB"));
    }
}
