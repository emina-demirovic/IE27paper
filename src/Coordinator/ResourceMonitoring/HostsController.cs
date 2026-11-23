using Contracts.ResourceMonitoring;
using Microsoft.AspNetCore.Mvc;

namespace Coordinator.ResourceMonitoring;

[ApiController]
[Route("api/hosts")]
public sealed class HostsController(HostResourceRegistry hostResources) : ControllerBase
{
    [HttpGet]
    public ActionResult<IReadOnlyCollection<HostResourceStatus>> GetAll()
    {
        return Ok(hostResources.GetAll());
    }
}
