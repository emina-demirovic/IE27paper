using System.Collections.Concurrent;
using System.Diagnostics;
using Scheduling;
using Coordinator.Data;
using Coordinator.Services;

namespace SchedulingV1;

// The coordinator owns both timestamps. Only this isolated host registers the
// policy and the MVC filter. A fresh instance is created for every batch.
internal sealed class BatchObservation(IReadOnlyDictionary<string, BatchTask> tasks, string policy)
    : CompletionClock(tasks.Count), IPendingExperimentPolicy
{
    private readonly ConcurrentDictionary<Guid, long> _dispatch = new();

    public ExperimentEntity? SelectNext(IEnumerable<ExperimentEntity> pending)
    {
        if (!Released)
            return null;

        var next = policy == "FIFO"
            ? pending.MinBy(row => tasks[row.Name].ArrivalIndex)
            : pending.MinBy(row => (-tasks[row.Name].K, tasks[row.Name].ArrivalIndex));

        // Timestamp the handoff to the scheduler's assignment command. The
        // runner also checks the persisted Assigned event and execution attempt.
        if (next is not null && !_dispatch.TryAdd(next.Id, Stopwatch.GetTimestamp()))
            Fail($"Repeated dispatch of {next.Name}.");
        return next;
    }

    public (double Dispatch, double Completion) Times(Guid id) =>
        (Seconds(_dispatch[id]), Completion(id));
}
