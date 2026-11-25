// Darwin CPU seconds. This runner's only subprocesses are the V2 executors.
// The load group is launched by the driver, as a sibling of the runner.
#include <libproc.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <sys/resource.h>
#include <unistd.h>

static int usage(pid_t pid, struct rusage_info_v1 *r) {
    return proc_pid_rusage(pid, RUSAGE_INFO_V1, (rusage_info_t *)r);
}

// Sum live descendants and the kernel's final counters for reaped descendants.
// Retry the whole read if a reap moves CPU from a child into its parent mid-walk.
static int tree(pid_t pid, int include_self, int depth, uint64_t *ticks) {
    struct rusage_info_v1 before, after;
    pid_t children[64];
    if (depth > 12 || usage(pid, &before)) return -1;
    // A zombie's cached rusage already includes its waited descendants.
    int n = before.ri_proc_exit_abstime ? 0 : proc_listchildpids(pid, children, sizeof(children));
    if (n < 0 || n >= 64) return -1;
    uint64_t live = 0;
    for (int i = 0; i < n; ++i) {
        struct proc_bsdinfo identity;
        if (proc_pidinfo(children[i], PROC_PIDTBSDINFO, 0, &identity, sizeof(identity)) != sizeof(identity)
            || identity.pbi_ppid != (uint32_t)pid || tree(children[i], 1, depth + 1, &live)) return -1;
    }
    if (usage(pid, &after) || before.ri_proc_start_abstime != after.ri_proc_start_abstime ||
        before.ri_child_user_time != after.ri_child_user_time ||
        before.ri_child_system_time != after.ri_child_system_time) return -1;
    *ticks += live + after.ri_child_user_time + after.ri_child_system_time;
    if (include_self) *ticks += after.ri_user_time + after.ri_system_time;
    return 0;
}

int v31_counters(int load_pid, double *host, double *work, double *load) {
    processor_info_array_t info;
    mach_msg_type_number_t count;
    natural_t ncpu;
    mach_port_t port = mach_host_self();
    kern_return_t result = host_processor_info(port, PROCESSOR_CPU_LOAD_INFO, &ncpu, &info, &count);
    mach_port_deallocate(mach_task_self(), port);
    if (result != KERN_SUCCESS) return -1;
    processor_cpu_load_info_t cpu = (processor_cpu_load_info_t)info;
    double busy_ticks = 0;
    for (unsigned i = 0; i < ncpu; ++i)
        busy_ticks += (double)cpu[i].cpu_ticks[CPU_STATE_USER] + cpu[i].cpu_ticks[CPU_STATE_SYSTEM]
                      + cpu[i].cpu_ticks[CPU_STATE_NICE];
    vm_deallocate(mach_task_self(), (vm_address_t)info, count * sizeof(*info));
    long hz = sysconf(_SC_CLK_TCK);
    mach_timebase_info_data_t scale;
    if (hz <= 0 || mach_timebase_info(&scale)) return -1;
    *host = busy_ticks / hz;
    for (int attempt = 0; attempt < 4; ++attempt) {
        uint64_t w = 0, l = 0;
        if (!tree(getpid(), 0, 0, &w) && (!load_pid || !tree(load_pid, 1, 0, &l))) {
            double seconds = (double)scale.numer / scale.denom / 1e9;
            *work = w * seconds;
            *load = l * seconds;
            return 0;
        }
        if (attempt < 3) usleep(1000); // Allow an in-flight fork/reap to finish.
    }
    return -1;
}
