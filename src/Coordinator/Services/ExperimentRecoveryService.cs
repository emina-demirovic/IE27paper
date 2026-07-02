using Contracts;
using Coordinator.Commands;

namespace Coordinator.Services;

public sealed class ExperimentRecoveryService(
    ILogger<ExperimentRecoveryService> logger,
    WorkerRegistry workerRegistry,
    ExperimentRegistry experimentRegistry,
    CoordinatorCommandProcessor commandProcessor)
    : BackgroundService
{
    protected override async Task ExecuteAsync(
        CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            var runningExperiments =
                experimentRegistry.GetRunning();

            foreach (var experiment in runningExperiments)
            {
                var workerId =
                    experiment.AssignedWorkerId;

                if (string.IsNullOrWhiteSpace(workerId))
                {
                    continue;
                }

                if (workerRegistry.IsOnline(workerId))
                {
                    continue;
                }

                var command =
                    new RequeueExperimentCommand(
                        CommandId: Guid.NewGuid(),
                        OccurredAtUtc:
                            DateTimeOffset.UtcNow,
                        ExperimentId: experiment.Id,
                        EventId: Guid.NewGuid(),
                        WorkerId: workerId,
                        Attempt: experiment.Attempt,
                        CancelInsteadOfRequeue:
                            experiment.CancellationRequested);

                try
                {
                    var result =
                        commandProcessor.Apply(command);

                    if (result.Value.Status ==
                        ExperimentStatus.Cancelled)
                    {
                        logger.LogWarning(
                            "Experiment {ExperimentId} was " +
                            "cancelled because worker " +
                            "{WorkerId} is offline.",
                            experiment.Id,
                            workerId);
                    }
                    else
                    {
                        logger.LogWarning(
                            "Experiment {ExperimentId} returned " +
                            "to Pending because worker " +
                            "{WorkerId} is offline.",
                            experiment.Id,
                            workerId);
                    }
                }
                catch (InvalidOperationException exception)
                {
                    logger.LogDebug(
                        exception,
                        "Recovery of experiment {ExperimentId} " +
                        "was skipped.",
                        experiment.Id);
                }
            }

            try
            {
                await Task.Delay(
                    TimeSpan.FromSeconds(2),
                    stoppingToken);
            }
            catch (OperationCanceledException)
                when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
        }
    }
}