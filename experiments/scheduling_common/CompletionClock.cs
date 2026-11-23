using System.Collections.Concurrent;
using System.Diagnostics;
using Coordinator.Controllers;
using Microsoft.AspNetCore.Mvc.Controllers;
using Microsoft.AspNetCore.Mvc.Filters;

namespace Scheduling;

internal class CompletionClock(int count) : IAsyncResourceFilter
{
    private long _start;
    private readonly ConcurrentDictionary<Guid, long> _completion = new();
    private readonly TaskCompletionSource _finished = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public Task Finished => _finished.Task;
    public bool Released => Volatile.Read(ref _start) != 0;
    public void Release() => Interlocked.Exchange(ref _start, Stopwatch.GetTimestamp());
    public double Seconds(long ticks) => Stopwatch.GetElapsedTime(_start, ticks).TotalSeconds;
    public double Completion(Guid id) => Seconds(_completion[id]);
    protected void Fail(string message) => _finished.TrySetException(new InvalidOperationException(message));

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
        else if (_completion.Count == count)
        {
            _finished.TrySetResult();
        }
    }

}
