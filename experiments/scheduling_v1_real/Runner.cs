using Contracts;
using Microsoft.Extensions.Configuration;
using Scheduling;
using System.Net.Http.Json;
using System.Text.Json;
using Worker.Execution;

namespace SchedulingV1;

internal sealed record BatchTask(string Id, int ArrivalIndex, double K, string Algorithm, string Environment, int MaxSteps, int Seed);
internal static class Runner
{
    public static async Task Main(string[] args)
    {
        var jobs = JsonSerializer.Deserialize<BatchTask[]>(File.ReadAllText(args[0]))!;
        var policy = args[1];
        if (policy is not ("FIFO" or "LPT") || jobs.Any(j => !double.IsFinite(j.K) || j.K <= 0) ||
            !jobs.Select(j => j.ArrivalIndex).SequenceEqual(Enumerable.Range(0, jobs.Length)))
            throw new InvalidDataException("Invalid policy, predictions or manifest indices.");
        var observation = new BatchObservation(jobs.ToDictionary(j => j.Id), policy);
        var settings = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string,string?> {
            ["Worker:Executor:PythonCommand"] = args[3],
            ["Worker:Executor:ScriptPath"] = Path.GetFullPath("../../src/Worker/Scripts/run_experiment.py")
        }).Build();
        var requests = jobs.Select(j => new CreateExperimentRequest {
            Name = j.Id, Algorithm = j.Algorithm, Environment = j.Environment,
            Seed = j.Seed, MaxSteps = j.MaxSteps, Priority = 1, TimeoutSeconds = 480
        }).ToArray();
        await LocalBatch.RunAsync(requests, new PythonProcessExperimentExecutor(settings), observation,
            observation, true, TimeSpan.FromMinutes(10), async (client, _, workers) => {
                var completed = (await client.GetFromJsonAsync<ExperimentResponse[]>("/api/experiments"))!;
                var ordered = completed.OrderBy(t => observation.Times(t.Id).Dispatch).ToArray();
                var expected = policy == "FIFO" ? jobs.AsEnumerable() : jobs.OrderByDescending(j => j.K).ThenBy(j => j.ArrivalIndex);
                if (!expected.Select(j => j.Id).SequenceEqual(ordered.Select(t => t.Name)))
                    throw new InvalidDataException("Unexpected dispatch order.");
                var last = new Dictionary<string,double>();
                var rows = new List<object>();
                foreach (var t in ordered)
                {
                    var (dispatch, completion) = observation.Times(t.Id);
                    var worker = t.AssignedWorkerId;
                    if (t.Status != ExperimentStatus.Completed || t.Attempt != 1 || t.ExecutionDurationMs is null or <= 0 ||
                        worker is null || !workers.Contains(worker) || dispatch < last.GetValueOrDefault(worker) || dispatch >= completion ||
                        string.IsNullOrWhiteSpace(t.MetricsJson))
                        throw new InvalidDataException($"Invalid completion for {t.Name}: {t.ResultMessage}");
                    last[worker] = completion;
                    rows.Add(new { t.Name, worker, dispatch, completion, t.ExecutionDurationMs,
                        metrics = JsonSerializer.Deserialize<JsonElement>(t.MetricsJson) });
                }
                File.WriteAllText(args[2], JsonSerializer.Serialize(new {policy, makespan = last.Values.Max(), workers = last.Count, rows}));
                return true;
            }, CancellationToken.None);
    }
}
