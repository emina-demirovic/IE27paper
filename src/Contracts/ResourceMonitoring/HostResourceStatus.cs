namespace Contracts.ResourceMonitoring;

public sealed record HostResourceStatus(
    string HostId,
    HostResourceSample Sample,
    DateTimeOffset ReceivedAtUtc,
    bool IsStale);
