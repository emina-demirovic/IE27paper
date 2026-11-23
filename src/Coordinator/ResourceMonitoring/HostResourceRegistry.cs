using System.Collections.Concurrent;
using Contracts.ResourceMonitoring;

namespace Coordinator.ResourceMonitoring;

public sealed class HostResourceRegistry
{
    private static readonly TimeSpan FreshnessWindow = TimeSpan.FromSeconds(15);

    private readonly ConcurrentDictionary<string, HostResourceStatus> _latestByHost =
        new(StringComparer.Ordinal);

    public void Report(string hostId, HostResourceSample sample)
    {
        if (sample.MeasuredAtUtc == default ||
            (sample.CpuUsagePercent is double cpuUsage &&
                (!double.IsFinite(cpuUsage) || cpuUsage is < 0 or > 100)) ||
            sample.TotalMemoryBytes <= 0 ||
            sample.MemoryBytes < 0 ||
            sample.MemoryBytes > sample.TotalMemoryBytes ||
            string.IsNullOrWhiteSpace(sample.MemoryKind))
        {
            return;
        }

        var status = new HostResourceStatus(hostId, sample, DateTimeOffset.UtcNow, false);
        _latestByHost.AddOrUpdate(
            hostId,
            status,
            (_, current) => sample.MeasuredAtUtc > current.Sample.MeasuredAtUtc
                ? status
                : current);
    }

    public IReadOnlyCollection<HostResourceStatus> GetAll()
    {
        var now = DateTimeOffset.UtcNow;
        return _latestByHost.Values
            .OrderBy(status => status.HostId, StringComparer.Ordinal)
            .Select(status => status with { IsStale = now - status.ReceivedAtUtc > FreshnessWindow })
            .ToArray();
    }
}
