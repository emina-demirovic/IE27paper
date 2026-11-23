using System.Runtime.InteropServices;
using Contracts.ResourceMonitoring;

namespace Worker.ResourceMonitoring;

internal sealed class MacHostResourceMonitor : IHostResourceMonitor
{
    private const string SystemLibrary = "/usr/lib/libSystem.B.dylib";
    private const int HostCpuLoadInfo = 3;
    private const int HostVmInfo64 = 4;
    private const uint CpuInfoCount = 4;
    private const uint VmInfoRevision0Count = 24;

    // Keep one Mach host port for the lifetime of the Worker process.
    private uint _hostPort;
    private long _totalMemoryBytes;
    private long _pageSize;
    private CpuTicks? _previousCpuTicks;

    public HostResourceSample Collect()
    {
        if (_hostPort == 0)
        {
            _hostPort = mach_host_self();
            if (_hostPort == 0)
            {
                throw new InvalidOperationException("Could not acquire the Mach host port.");
            }
        }

        if (_totalMemoryBytes == 0)
        {
            nuint size = sizeof(long);
            if (sysctlbyname("hw.memsize", out var totalMemory, ref size, 0, 0) != 0)
            {
                throw new InvalidOperationException(
                    $"Could not read hw.memsize. errno={Marshal.GetLastPInvokeError()}.");
            }

            if (size != sizeof(long) || totalMemory <= 0)
            {
                throw new InvalidOperationException("hw.memsize returned invalid data.");
            }

            _totalMemoryBytes = totalMemory;
        }

        if (_pageSize == 0)
        {
            EnsureSuccess(host_page_size(_hostPort, out var pageSize), "host_page_size");
            _pageSize = checked((long)pageSize);
        }

        var vmCount = VmInfoRevision0Count;
        EnsureSuccess(
            host_statistics64(_hostPort, HostVmInfo64, out var memory, ref vmCount),
            "host_statistics64");

        var cpuCount = CpuInfoCount;
        EnsureSuccess(
            host_statistics(_hostPort, HostCpuLoadInfo, out var cpu, ref cpuCount),
            "host_statistics");

        var cpuUsage = _previousCpuTicks is { } previous
            ? CalculateCpuUsage(previous, cpu)
            : null;
        _previousCpuTicks = cpu;

        return new HostResourceSample(
            DateTimeOffset.UtcNow,
            cpuUsage,
            _totalMemoryBytes,
            memory.FreePages * _pageSize,
            "free");
    }

    private static double? CalculateCpuUsage(CpuTicks previous, CpuTicks current)
    {
        // Mach exposes cumulative 32-bit ticks, which can wrap between reads.
        var busy =
            (ulong)unchecked(current.User - previous.User) +
            unchecked(current.System - previous.System) +
            unchecked(current.Nice - previous.Nice);
        var total = busy + unchecked(current.Idle - previous.Idle);

        return total == 0 ? null : 100.0 * busy / total;
    }

    private static void EnsureSuccess(int result, string operation)
    {
        if (result != 0)
        {
            throw new InvalidOperationException($"{operation} failed with Mach status {result}.");
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct CpuTicks
    {
        public uint User;
        public uint System;
        public uint Idle;
        public uint Nice;
    }

    // Revision 0 of vm_statistics64 occupies 24 Mach integers.
    // The free count includes speculative pages.
    [StructLayout(LayoutKind.Explicit, Size = (int)VmInfoRevision0Count * sizeof(int))]
    private struct VmStatistics
    {
        [FieldOffset(0)]
        public uint FreePages;
    }

    [DllImport(SystemLibrary, ExactSpelling = true)]
    private static extern uint mach_host_self();

    [DllImport(SystemLibrary, ExactSpelling = true)]
    private static extern int host_page_size(uint host, out nuint pageSize);

    [DllImport(SystemLibrary, ExactSpelling = true)]
    private static extern int host_statistics(uint host, int flavor, out CpuTicks info, ref uint count);

    [DllImport(SystemLibrary, ExactSpelling = true)]
    private static extern int host_statistics64(uint host, int flavor, out VmStatistics info, ref uint count);

    [DllImport(SystemLibrary, ExactSpelling = true, SetLastError = true)]
    private static extern int sysctlbyname(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string name,
        out long value,
        ref nuint size,
        nint newValue,
        nuint newSize);
}
