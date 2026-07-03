using System.Net;
using System.Net.Http.Json;
using Contracts;
using Coordinator.Raft;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Coordinator.Tests.Raft;

public sealed class RaftCreateExperimentEndpointTests
{
    [Fact]
    public async Task CreateExperiment_WithRaftEnabled_UsesLeaderSubmission()
    {
        using var factory =
            CreateRaftEnabledFactory();

        using var client =
            factory.CreateClient();

        var nodeState =
            factory.Services
                .GetRequiredService<
                    RaftNodeState>();

        var election =
            nodeState.BeginElection();

        Assert.True(
            nodeState.TryBecomeLeader(
                election.CurrentTerm));

        var response =
            await client.PostAsJsonAsync(
                "/api/experiments",
                new
                {
                    name = "Raft API experiment",
                    algorithm = "PPO",
                    environment = "CartPole-v1",
                    seed = 42,
                    maxSteps = 1000,
                    priority = 1,
                    timeoutSeconds = 300,
                    simulateFailure = false
                });

        Assert.Equal(
            HttpStatusCode.Created,
            response.StatusCode);

        var experiment =
            await response.Content
                .ReadFromJsonAsync<
                    ExperimentResponse>();

        Assert.NotNull(experiment);

        Assert.Equal(
            "Raft API experiment",
            experiment.Name);

        var commitState =
            factory.Services
                .GetRequiredService<
                    RaftCommitManager>()
                .GetState();

        Assert.Equal(1, commitState.CommitIndex);
        Assert.Equal(1, commitState.LastApplied);
    }

    [Fact]
    public async Task CreateExperiment_WithRaftEnabledOnFollower_ReturnsConflict()
    {
        using var factory =
            CreateRaftEnabledFactory();

        using var client =
            factory.CreateClient();

        var response =
            await client.PostAsJsonAsync(
                "/api/experiments",
                new
                {
                    name = "Follower rejected experiment",
                    algorithm = "PPO",
                    environment = "CartPole-v1",
                    seed = 42,
                    maxSteps = 1000,
                    priority = 1,
                    timeoutSeconds = 300,
                    simulateFailure = false
                });

        Assert.Equal(
            HttpStatusCode.Conflict,
            response.StatusCode);

        var logStore =
            factory.Services
                .GetRequiredService<
                    IRaftLogStore>();

        Assert.Null(
            logStore.GetLast());
    }

    private static WebApplicationFactory<Program>
        CreateRaftEnabledFactory()
    {
        return new CoordinatorWebApplicationFactory()
            .WithWebHostBuilder(
                builder =>
                {
                    builder.ConfigureAppConfiguration(
                        (_, configuration) =>
                        {
                            configuration.AddInMemoryCollection(
                                new Dictionary<string, string?>
                                {
                                    ["Raft:ClientCommandReplicationEnabled"] =
                                        "true",
                                    ["Raft:CommandReplicationTimeoutMilliseconds"] =
                                        "500",
                                    ["Raft:CommandReplicationPollMilliseconds"] =
                                        "10"
                                });
                        });

                    builder.ConfigureServices(
                        services =>
                        {
                            services.RemoveAll<
                                IRaftPeerClient>();

                            services.AddSingleton<
                                IRaftPeerClient,
                                SuccessfulPeerClient>();
                        });
                });
    }

    private sealed class SuccessfulPeerClient
        : IRaftPeerClient
    {
        public Task<RequestVoteResponse>
            RequestVoteAsync(
                RaftPeerSnapshot peer,
                RequestVoteRequest request,
                CancellationToken cancellationToken)
        {
            return Task.FromResult(
                new RequestVoteResponse(
                    request.Term,
                    VoteGranted: true));
        }

        public Task<AppendEntriesResponse>
            AppendEntriesAsync(
                RaftPeerSnapshot peer,
                AppendEntriesRequest request,
                CancellationToken cancellationToken)
        {
            return Task.FromResult(
                new AppendEntriesResponse(
                    request.Term,
                    Success: true));
        }
    }
}