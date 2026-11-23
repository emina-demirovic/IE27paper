namespace Contracts.ResourceMonitoring;

public sealed record WorkerHeartbeatRequest(HostResourceSample? Resources);
