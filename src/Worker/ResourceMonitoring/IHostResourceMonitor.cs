using Contracts.ResourceMonitoring;

namespace Worker.ResourceMonitoring;

internal interface IHostResourceMonitor
{
    HostResourceSample Collect();
}
