namespace Contracts.ResourceMonitoring;

public sealed record HostResourceSample(
    DateTimeOffset MeasuredAtUtc,
    double? CpuUsagePercent,
    long TotalMemoryBytes,
    long MemoryBytes,
    string MemoryKind);
