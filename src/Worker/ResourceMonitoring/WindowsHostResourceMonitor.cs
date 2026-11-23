using System.ComponentModel;
using System.Runtime.InteropServices;
using Contracts.ResourceMonitoring;

namespace Worker.ResourceMonitoring;

internal sealed class WindowsHostResourceMonitor : IHostResourceMonitor
{
    private SystemTimes? _previousTimes;

    public HostResourceSample Collect()
    {
        // GetSystemTimes covers only the calling thread's group on multi-group hosts.
        if (_previousTimes is null && GetActiveProcessorGroupCount() != 1)
        {
            throw new InvalidOperationException(
                "Windows host monitoring requires a single processor group.");
        }

        var memory = new MemoryStatus { Length = (uint)Marshal.SizeOf<MemoryStatus>() };
        if (!GlobalMemoryStatusEx(ref memory))
        {
            throw new Win32Exception(Marshal.GetLastPInvokeError(), "GlobalMemoryStatusEx failed.");
        }

        if (!GetSystemTimes(out var idle, out var kernel, out var user))
        {
            throw new Win32Exception(Marshal.GetLastPInvokeError(), "GetSystemTimes failed.");
        }

        var current = new SystemTimes(idle.Ticks, kernel.Ticks, user.Ticks);
        var cpuUsage = _previousTimes is { } previous ? CalculateCpuUsage(previous, current) : null;
        _previousTimes = current;

        return new HostResourceSample(
            DateTimeOffset.UtcNow,
            cpuUsage,
            checked((long)memory.TotalPhysical),
            checked((long)memory.AvailablePhysical),
            "available");
    }

    internal static double? CalculateCpuUsage(SystemTimes previous, SystemTimes current)
    {
        if (current.Idle < previous.Idle ||
            current.Kernel < previous.Kernel ||
            current.User < previous.User)
        {
            return null;
        }

        var idle = current.Idle - previous.Idle;

        // Windows includes idle ticks in kernel time.
        var total = (current.Kernel - previous.Kernel) + (current.User - previous.User);
        return total == 0 || idle > total ? null : 100.0 * (total - idle) / total;
    }

    internal readonly record struct SystemTimes(ulong Idle, ulong Kernel, ulong User);

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public uint Low;
        public uint High;

        public readonly ulong Ticks => ((ulong)High << 32) | Low;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MemoryStatus
    {
        public uint Length;
        public uint MemoryLoad;
        public ulong TotalPhysical;
        public ulong AvailablePhysical;
        public ulong TotalPageFile;
        public ulong AvailablePageFile;
        public ulong TotalVirtual;
        public ulong AvailableVirtual;
        public ulong AvailableExtendedVirtual;
    }

    [DllImport("kernel32.dll", ExactSpelling = true)]
    private static extern ushort GetActiveProcessorGroupCount();

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetSystemTimes(out FileTime idle, out FileTime kernel, out FileTime user);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatus memory);
}
