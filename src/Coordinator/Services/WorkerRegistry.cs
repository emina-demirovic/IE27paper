using System.Collections.Concurrent;
using Contracts;

namespace Coordinator.Services;

public sealed class WorkerRegistry
{
    private static readonly TimeSpan OnlineTimeout =
        TimeSpan.FromSeconds(15);

    private readonly ConcurrentDictionary<string, WorkerStatusResponse> _workers =
        new();

    public WorkerStatusResponse Register(string workerId, string? hostId = null)
    {
        var now = DateTimeOffset.UtcNow;

        return _workers.AddOrUpdate(
            workerId,
            _ => new WorkerStatusResponse
            {
                WorkerId = workerId,
                HostId = hostId,
                RegisteredAtUtc = now,
                LastHeartbeatAtUtc = now,
                IsOnline = true
            },
            (_, existingWorker) => new WorkerStatusResponse
            {
                WorkerId = existingWorker.WorkerId,
                HostId = hostId,
                RegisteredAtUtc = existingWorker.RegisteredAtUtc,
                LastHeartbeatAtUtc = now,
                IsOnline = true
            });
    }

    public WorkerStatusResponse? Heartbeat(string workerId)
    {
        while (_workers.TryGetValue(workerId, out var existingWorker))
        {
            var updatedWorker = new WorkerStatusResponse
            {
                WorkerId = existingWorker.WorkerId,
                HostId = existingWorker.HostId,
                RegisteredAtUtc = existingWorker.RegisteredAtUtc,
                LastHeartbeatAtUtc = DateTimeOffset.UtcNow,
                IsOnline = true
            };

            if (_workers.TryUpdate(workerId, updatedWorker, existingWorker))
            {
                return updatedWorker;
            }
        }

        return null;
    }

    public WorkerStatusResponse? GetFirstOnline()
    {
        var now = DateTimeOffset.UtcNow;

        return _workers.Values
            .Where(worker =>
                now - worker.LastHeartbeatAtUtc <= OnlineTimeout)
            .OrderBy(worker => worker.WorkerId)
            .Select(worker => new WorkerStatusResponse
            {
                WorkerId = worker.WorkerId,
                HostId = worker.HostId,
                RegisteredAtUtc = worker.RegisteredAtUtc,
                LastHeartbeatAtUtc = worker.LastHeartbeatAtUtc,
                IsOnline = true
            })
            .FirstOrDefault();
    }

    public IReadOnlyCollection<WorkerStatusResponse> GetOnlineWorkers()
    {
        var now = DateTimeOffset.UtcNow;

        return _workers.Values
            .Where(worker =>
                now - worker.LastHeartbeatAtUtc <= OnlineTimeout)
            .OrderBy(worker => worker.WorkerId)
            .Select(worker => new WorkerStatusResponse
            {
                WorkerId = worker.WorkerId,
                HostId = worker.HostId,
                RegisteredAtUtc = worker.RegisteredAtUtc,
                LastHeartbeatAtUtc = worker.LastHeartbeatAtUtc,
                IsOnline = true
            })
            .ToArray();
    }
    
    public IReadOnlyCollection<WorkerStatusResponse> GetAll()
    {
        var now = DateTimeOffset.UtcNow;

        return _workers.Values
            .Select(worker => new WorkerStatusResponse
            {
                WorkerId = worker.WorkerId,
                HostId = worker.HostId,
                RegisteredAtUtc = worker.RegisteredAtUtc,
                LastHeartbeatAtUtc = worker.LastHeartbeatAtUtc,
                IsOnline = now - worker.LastHeartbeatAtUtc <= OnlineTimeout
            })
            .OrderBy(worker => worker.WorkerId)
            .ToArray();
    }

    public bool IsOnline(string workerId)
    {
        if (!_workers.TryGetValue(workerId, out var worker))
        {
            return false;
        }

        return DateTimeOffset.UtcNow - worker.LastHeartbeatAtUtc
            <= OnlineTimeout;
    }
    
}