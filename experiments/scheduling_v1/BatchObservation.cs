using System.Collections.Concurrent;
using System.Diagnostics;
using Coordinator.Controllers;
using Coordinator.Data;
using Coordinator.Services;
using Microsoft.AspNetCore.Mvc.Controllers;
using Microsoft.AspNetCore.Mvc.Filters;

namespace SchedulingV1;

// The coordinator owns both timestamps. Only this isolated host registers the
// policy and the MVC filter. A fresh instance is created for every batch.
internal sealed class BatchObservation(IReadOnlyDictionary<string, BatchTask> tasks, string policy)
    : IPendingExperimentPolicy, IAsyncResourceFilter
{
    private long _start;
    private readonly ConcurrentDictionary<Guid, long> _dispatch = new();
    private readonly ConcurrentDictionary<Guid, long> _completion = new();
    private readonly TaskCompletionSource _finished = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public Task Finished => _finished.Task;

    public void Release() => Interlocked.Exchange(ref _start, Stopwatch.GetTimestamp());

    public ExperimentEntity? SelectNext(IEnumerable<ExperimentEntity> pending)
    {
        if (Volatile.Read(ref _start) == 0)
            return null;

        var next = policy == "FIFO"
            ? pending.MinBy(row => tasks[row.Name].ArrivalIndex)
            : pending.MinBy(row => (-tasks[row.Name].K, tasks[row.Name].ArrivalIndex));

        // Timestamp the handoff to the scheduler's assignment command. The
        // runner also checks the persisted Assigned event and execution attempt.
        if (next is not null && !_dispatch.TryAdd(next.Id, Stopwatch.GetTimestamp()))
            _finished.TrySetException(new InvalidOperationException($"Repeated dispatch of {next.Name}."));
        return next;
    }

    public async Task OnResourceExecutionAsync(ResourceExecutingContext context, ResourceExecutionDelegate next)
    {
        if (context.ActionDescriptor is not ControllerActionDescriptor action ||
            action.ControllerTypeInfo.AsType() != typeof(ExperimentsController) ||
            action.ActionName != nameof(ExperimentsController.Complete))
        {
            await next();
            return;
        }

        // Before request-body binding. Count the timestamp only after the
        // normal completion endpoint has accepted and persisted the report.
        long received = Stopwatch.GetTimestamp();
        var id = Guid.Parse((string)context.RouteData.Values["id"]!);
        var result = await next();
        if (result.Exception is not null || context.HttpContext.Response.StatusCode != 200 ||
            !_completion.TryAdd(id, received))
        {
            _finished.TrySetException(new InvalidOperationException($"Rejected or duplicate completion for {id}."));
        }
        else if (_completion.Count == tasks.Count)
        {
            _finished.TrySetResult();
        }
    }

    public (double Dispatch, double Completion) Times(Guid id) => (
        Stopwatch.GetElapsedTime(_start, _dispatch[id]).TotalSeconds,
        Stopwatch.GetElapsedTime(_start, _completion[id]).TotalSeconds);
}
