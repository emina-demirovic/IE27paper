namespace Coordinator.Raft;

public sealed class RaftOptions
{
    public const string SectionName = "Raft";

    public string NodeId { get; set; } = string.Empty;

    public int HeartbeatIntervalMilliseconds { get; set; } = 500;
    
    public List<RaftPeerOptions> Peers { get; set; } = [];

    public bool AutomaticElectionEnabled { get; set; }

    public int ElectionTimeoutMinMilliseconds { get; set; } = 1500;

    public int ElectionTimeoutMaxMilliseconds { get; set; } = 3000;
}