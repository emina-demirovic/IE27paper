namespace Coordinator.Raft;

public sealed class RaftHeartbeatSender(
    RaftNodeState nodeState,
    IRaftPeerClient peerClient)
{
    public async Task SendHeartbeatAsync(
        CancellationToken cancellationToken = default)
    {
        var leaderSnapshot =
            nodeState.GetSnapshot();

        if (leaderSnapshot.Role !=
            RaftNodeRole.Leader)
        {
            return;
        }

        var request =
            new AppendEntriesRequest(
                Term:
                    leaderSnapshot.CurrentTerm,
                LeaderId:
                    leaderSnapshot.NodeId,
                PrevLogIndex: 0,
                PrevLogTerm: 0,
                LeaderCommit: 0);

        var responseTasks =
            leaderSnapshot.Peers
                .Select(peer =>
                    AppendEntriesSafelyAsync(
                        peer,
                        request,
                        cancellationToken))
                .ToArray();

        var responses =
            await Task.WhenAll(responseTasks);

        var highestObservedTerm =
            responses
                .Where(response =>
                    response is not null)
                .Select(response =>
                    response!.Term)
                .DefaultIfEmpty(
                    leaderSnapshot.CurrentTerm)
                .Max();

        if (highestObservedTerm >
            leaderSnapshot.CurrentTerm)
        {
            nodeState.ObserveHigherTerm(
                highestObservedTerm);
        }
    }

    private async Task<AppendEntriesResponse?>
        AppendEntriesSafelyAsync(
            RaftPeerSnapshot peer,
            AppendEntriesRequest request,
            CancellationToken cancellationToken)
    {
        try
        {
            return await peerClient.AppendEntriesAsync(
                peer,
                request,
                cancellationToken);
        }
        catch (HttpRequestException)
        {
            return null;
        }
        catch (OperationCanceledException)
            when (!cancellationToken
                .IsCancellationRequested)
        {
            return null;
        }
    }
}