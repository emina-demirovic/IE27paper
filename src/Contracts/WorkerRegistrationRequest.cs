namespace Contracts;

public sealed class WorkerRegistrationRequest
{
    public string WorkerId { get; set; } = string.Empty;

    public string? HostId { get; set; }
}