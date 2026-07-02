using Coordinator.Commands;

namespace Coordinator.Services;

public sealed class ExperimentSchedulerService(
    ILogger<ExperimentSchedulerService> logger,
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
            var onlineWorkers =
                workerRegistry.GetOnlineWorkers();

            foreach (var worker in onlineWorkers)
            {
                if (experimentRegistry.HasRunningExperiment(
                    worker.WorkerId))
                {
                    continue;
                }

                while (true)
                {
                    var pendingExperiment =
                        experimentRegistry.GetNextPending();

                    if (pendingExperiment is null)
                    {
                        break;
                    }

                    var command =
                        new AssignExperimentCommand(
                            CommandId: Guid.NewGuid(),
                            OccurredAtUtc:
                                DateTimeOffset.UtcNow,
                            ExperimentId:
                                pendingExperiment.Id,
                            EventId: Guid.NewGuid(),
                            WorkerId: worker.WorkerId,
                            Attempt:
                                pendingExperiment.Attempt + 1);

                    try
                    {
                        var result =
                            commandProcessor.Apply(command);

                        logger.LogInformation(
                            "Experiment {ExperimentId} " +
                            "automatically assigned to worker " +
                            "{WorkerId}.",
                            result.Value.Id,
                            worker.WorkerId);

                        break;
                    }
                    catch (InvalidOperationException exception)
                    {
                        logger.LogDebug(
                            exception,
                            "Automatic assignment of experiment " +
                            "{ExperimentId} was skipped.",
                            pendingExperiment.Id);
                    }
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