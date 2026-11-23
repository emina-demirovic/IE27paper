using Contracts;
using Contracts.ResourceMonitoring;
using Coordinator.ResourceMonitoring;
using Coordinator.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;

namespace Coordinator.Controllers;

[ApiController]
[Route("api/workers")]
public sealed class WorkersController : ControllerBase
{
    private readonly WorkerRegistry _workerRegistry;
    private readonly HostResourceRegistry _hostResources;

    public WorkersController(
        WorkerRegistry workerRegistry,
        HostResourceRegistry hostResources)
    {
        _workerRegistry = workerRegistry;
        _hostResources = hostResources;
    }

    [HttpPost("register")]
    public ActionResult<WorkerStatusResponse> Register(
        WorkerRegistrationRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.WorkerId))
        {
            return BadRequest("WorkerId is required.");
        }

        var worker = _workerRegistry.Register(
            request.WorkerId,
            string.IsNullOrWhiteSpace(request.HostId) ? null : request.HostId.Trim());

        return Ok(worker);
    }

    [HttpPost("{workerId}/heartbeat")]
    public ActionResult<WorkerStatusResponse> Heartbeat(
        string workerId,
        [FromBody(EmptyBodyBehavior = EmptyBodyBehavior.Allow)] WorkerHeartbeatRequest? request)
    {
        if (string.IsNullOrWhiteSpace(workerId))
        {
            return BadRequest("WorkerId is required.");
        }

        var worker = _workerRegistry.Heartbeat(workerId);

        if (worker is null)
        {
            return NotFound($"Worker '{workerId}' is not registered.");
        }

        if (worker.HostId is { } hostId && request?.Resources is { } sample)
        {
            _hostResources.Report(hostId, sample);
        }

        return Ok(worker);
    }

    [HttpGet]
    public ActionResult<IReadOnlyCollection<WorkerStatusResponse>> GetAll()
    {
        return Ok(_workerRegistry.GetAll());
    }
}