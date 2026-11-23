using System.Net.Http.Json;
using Contracts;
using Scheduling;

namespace SchedulingV1;

internal static class Platform
{
    public static Task<double> RunAsync(BatchTask[] order, string scenario, string policy,
        string runId, string directory, int millisecondsPerSecond, bool inProcess, CancellationToken token)
    {
        var tasks = order.ToDictionary(task => task.Id);
        var observation = new BatchObservation(tasks, policy);
        var requests = order.Select(task => new CreateExperimentRequest
        {
            Name = task.Id, Algorithm = "scheduling-v1-delay", Environment = "local",
            MaxSteps = 1, Priority = 1, TimeoutSeconds = 120
        }).ToArray();
        var deadline = TimeSpan.FromSeconds(90 + 2 * Workload.IdealMakespan(order, policy)
            * millisecondsPerSecond / 1000.0);
        return LocalBatch.RunAsync(requests, new KnownDurationExecutor(tasks, millisecondsPerSecond),
            observation, observation, inProcess, deadline,
            (client, _, workers) => ValidateAndExport(client, observation, tasks, workers, directory,
                runId, scenario, policy, millisecondsPerSecond, token), token);
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
