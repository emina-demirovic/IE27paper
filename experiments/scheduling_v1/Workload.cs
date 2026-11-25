using System.Diagnostics;
using System.Globalization;
using Contracts;
using Worker.Execution;

namespace SchedulingV1;

internal record BatchTask(string Id, int ArrivalIndex, int K);

internal static class Workload
{
    public const int WorkerCount = 10;
    public const int ShuffleSeed = 2701;

    public static BatchTask[] Generate(string scenario)
    {
        int[] slow = [30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 60];
        var tasks = Enumerable.Range(1, 100).Select(i => (Id: $"fast-{i:D3}", K: 1))
            .Concat(slow.Select(k => (Id: $"slow-{k}", K: k))).ToArray();
        if (scenario == "B")
            new Random(ShuffleSeed).Shuffle(tasks);

        return tasks.Select((task, i) => new BatchTask(task.Id, i, task.K)).ToArray();
    }

    public static int IdealMakespan(BatchTask[] tasks, string policy)
    {
        var load = new int[WorkerCount];
        foreach (var task in policy == "FIFO" ? tasks.AsEnumerable() :
                     tasks.OrderByDescending(t => t.K).ThenBy(t => t.ArrivalIndex))
        {
            int firstAvailable = Array.IndexOf(load, load.Min());
            load[firstAvailable] += task.K;
        }
        return load.Max();
    }

    // These IDs and all cell values written by the runner are controlled
    // identifiers or numbers. Use invariant, round-trip numeric formatting.
    public static void WriteCsv(string path, string header, IEnumerable<string> rows) =>
        File.WriteAllLines(path, rows.Prepend(header));

    public static string Row(FormattableString row) => row.ToString(CultureInfo.InvariantCulture);
}

internal sealed class KnownDurationExecutor(
    IReadOnlyDictionary<string, BatchTask> tasks, int millisecondsPerSecond) : IExperimentExecutor
{
    public async Task<ExperimentExecutionResult> ExecuteAsync(
        ExperimentResponse experiment, Func<ExperimentProgressUpdate, CancellationToken, Task> reportProgressAsync,
        CancellationToken cancellationToken)
    {
        var start = Stopwatch.GetTimestamp();
        await Task.Delay(tasks[experiment.Name].K * millisecondsPerSecond, cancellationToken);
        return new(true, "Completed known-duration delay.", null,
            (long)Stopwatch.GetElapsedTime(start).TotalMilliseconds);
    }
}
