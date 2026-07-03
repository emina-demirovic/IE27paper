using Microsoft.Extensions.Options;

namespace Coordinator.Raft;

public sealed class RaftNodeState
{
    private readonly object _sync = new();

    private readonly string _nodeId;

    private readonly RaftPeerSnapshot[] _peers;

    private readonly IRaftPersistentStateStore
        _persistentStateStore;

    private RaftNodeRole _role =
        RaftNodeRole.Follower;

    private long _currentTerm;

    private string? _votedFor;

    private string? _leaderId;

    private readonly TimeProvider _timeProvider;

    private DateTimeOffset _lastElectionActivityUtc;

    public RaftNodeState(
        IOptions<RaftOptions> options,
        IRaftPersistentStateStore persistentStateStore,
        TimeProvider? timeProvider = null)
    {
        var raftOptions = options.Value;

        _nodeId = raftOptions.NodeId;

        _peers = raftOptions.Peers
            .Select(peer =>
                new RaftPeerSnapshot(
                    peer.NodeId,
                    peer.BaseUrl))
            .ToArray();

        _timeProvider =
            timeProvider ?? TimeProvider.System;

        _lastElectionActivityUtc =
            _timeProvider.GetUtcNow();    

        _persistentStateStore =
            persistentStateStore;

        var persistentState =
            _persistentStateStore.LoadOrCreate(
                _nodeId);

        _currentTerm =
            persistentState.CurrentTerm;

        _votedFor =
            persistentState.VotedFor;
    }

    public RaftNodeSnapshot GetSnapshot()
    {
        lock (_sync)
        {
            return CreateSnapshot();
        }
    }

    public RaftNodeSnapshot BeginElection()
    {
        lock (_sync)
        {
            var nextTerm =
                checked(_currentTerm + 1);

            _persistentStateStore.Save(
                _nodeId,
                nextTerm,
                _nodeId);

            _currentTerm = nextTerm;
            _votedFor = _nodeId;
            _role = RaftNodeRole.Candidate;
            _leaderId = null;
            ResetElectionTimer();

            return CreateSnapshot();
        }
    }

    public void ObserveHigherTerm(long term)
    {
        if (term < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(term));
        }

        lock (_sync)
        {
            if (term <= _currentTerm)
            {
                return;
            }

            _persistentStateStore.Save(
                _nodeId,
                term,
                votedFor: null);

            _currentTerm = term;
            _votedFor = null;
            _role = RaftNodeRole.Follower;
            _leaderId = null;
            ResetElectionTimer();
        }
    }

    public bool TryBecomeLeader(
        long electionTerm)
    {
        lock (_sync)
        {
            if (_currentTerm != electionTerm ||
                _role != RaftNodeRole.Candidate)
            {
                return false;
            }

            _role = RaftNodeRole.Leader;
            _leaderId = _nodeId;

            return true;
        }
    }

    public RequestVoteResponse HandleRequestVote(
        RequestVoteRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (request.Term < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(request),
                "Raft term cannot be negative.");
        }

        if (string.IsNullOrWhiteSpace(
            request.CandidateId))
        {
            throw new ArgumentException(
                "CandidateId is required.",
                nameof(request));
        }

        if (request.LastLogIndex < 0 ||
            request.LastLogTerm < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(request),
                "Raft log values cannot be negative.");
        }

        lock (_sync)
        {
            if (request.Term < _currentTerm)
            {
                return new RequestVoteResponse(
                    Term: _currentTerm,
                    VoteGranted: false);
            }

            if (request.Term > _currentTerm)
            {
                _persistentStateStore.Save(
                    _nodeId,
                    request.Term,
                    votedFor: null);

                _currentTerm = request.Term;
                _votedFor = null;
                _role = RaftNodeRole.Follower;
                _leaderId = null;
            }

            var canVote =
                _votedFor is null ||
                string.Equals(
                    _votedFor,
                    request.CandidateId,
                    StringComparison.Ordinal);

            var candidateLogIsUpToDate =
                IsCandidateLogUpToDate(
                    request.LastLogIndex,
                    request.LastLogTerm);

            if (!canVote ||
                !candidateLogIsUpToDate)
            {
                return new RequestVoteResponse(
                    Term: _currentTerm,
                    VoteGranted: false);
            }

            if (_votedFor is null)
            {
                _persistentStateStore.Save(
                    _nodeId,
                    _currentTerm,
                    request.CandidateId);

                _votedFor = request.CandidateId;
            }

            ResetElectionTimer();
            return new RequestVoteResponse(
                Term: _currentTerm,
                VoteGranted: true);
        }
    }

    public AppendEntriesResponse HandleAppendEntries(
        AppendEntriesRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (request.Term < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(request),
                "Raft term cannot be negative.");
        }

        if (string.IsNullOrWhiteSpace(
            request.LeaderId))
        {
            throw new ArgumentException(
                "LeaderId is required.",
                nameof(request));
        }

        if (request.PrevLogIndex < 0 ||
            request.PrevLogTerm < 0 ||
            request.LeaderCommit < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(request),
                "Raft log values cannot be negative.");
        }

        lock (_sync)
        {
            if (request.Term < _currentTerm)
            {
                return new AppendEntriesResponse(
                    Term: _currentTerm,
                    Success: false);
            }

            if (request.Term > _currentTerm)
            {
                _persistentStateStore.Save(
                    _nodeId,
                    request.Term,
                    votedFor: null);

                _currentTerm = request.Term;
                _votedFor = null;
            }

            _role = RaftNodeRole.Follower;
            _leaderId = request.LeaderId;
            ResetElectionTimer();

            var localLogMatches =
                request.PrevLogIndex == 0 &&
                request.PrevLogTerm == 0;

            return new AppendEntriesResponse(
                Term: _currentTerm,
                Success: localLogMatches);
        }
    }

    private static bool IsCandidateLogUpToDate(
        long candidateLastLogIndex,
        long candidateLastLogTerm)
    {
        const long localLastLogIndex = 0;
        const long localLastLogTerm = 0;

        return
            candidateLastLogTerm >
                localLastLogTerm ||
            (candidateLastLogTerm ==
                localLastLogTerm &&
            candidateLastLogIndex >=
                localLastLogIndex);
    }

    public bool HasElectionTimedOut(
        TimeSpan electionTimeout)
    {
        if (electionTimeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(electionTimeout));
        }

        lock (_sync)
        {
            if (_role == RaftNodeRole.Leader)
            {
                return false;
            }

            var elapsed =
                _timeProvider.GetUtcNow() -
                _lastElectionActivityUtc;

            return elapsed >= electionTimeout;
        }
    }

    private void ResetElectionTimer()
    {
        _lastElectionActivityUtc =
            _timeProvider.GetUtcNow();
    }

    private RaftNodeSnapshot CreateSnapshot()
    {
        return new RaftNodeSnapshot(
            NodeId: _nodeId,
            Role: _role,
            CurrentTerm: _currentTerm,
            VotedFor: _votedFor,
            LeaderId: _leaderId,
            Peers: _peers.ToArray());
    }
}