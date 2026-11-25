using Coordinator.Data;

namespace Coordinator.Services;

public interface IPendingExperimentPolicy
{
    ExperimentEntity? SelectNext(IEnumerable<ExperimentEntity> pending);
}
