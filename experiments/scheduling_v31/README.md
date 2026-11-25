# Scheduling V3.1 · external CPU load

Does the same 115-job batch finish sooner when LPT-KP accounts for CPU activity outside the matrix processes? Each pair runs fixed-budget V2 (`LPT-KP`) and adaptive V3.1 (`CPU-LPT-KP`) on the same Mac. Both use the V2 coordinator, ten WorkerService instances, SQLite reservations, Python executor, BLAS environment and completion clock. The driver copies the bytes of a saved V2 manifest and calibration, checks their relationship and validates the BLAS backend before starting. Full runs require the original 115 jobs. Smoke uses V2's smaller 18-job manifest.

## Run on this Mac

From the IE27paper repository root, select the Python and BLAS used for the saved V2 calibration. The launcher uses the same local .NET 10 SDK as V2 and builds a small Darwin counter library with the Xcode command-line tools.

```bash
export SCHED_V2_PYTHON="$HOME/ie27-ml-env/bin/python"
export SCHED_V2_OPENBLAS="/Applications/Julia-1.11.app/Contents/Resources/julia/lib/julia/libopenblas64_.dylib"
runner=experiments/scheduling_v31/run.sh
session=experiments/scheduling_v2/results/20261123T221514Z-full-dcfe33d39b

bash "$runner" test
bash "$runner" smoke --condition all --interval .2 --phase .3 --in-process

bash "$runner" full --v2-session "$session" --condition quiet --repeats 3
bash "$runner" full --v2-session "$session" --condition steady --repeats 3
bash "$runner" full --v2-session "$session" --condition changing --repeats 3

# All three conditions, three pairs each, in one session
bash "$runner" full --v2-session "$session" --condition all --repeats 3
```

On another Mac, select a matching saved V2 session and its environment. Without `--v2-session`, the driver takes the newest timestamped V2 full or smoke session matching the command. The default transport is Kestrel over loopback. `--in-process` uses ASP.NET TestServer and still launches each real GEMM in a separate Python process.

## CPU accounting and admission

One periodic task samples cumulative busy CPU-seconds from Darwin's per-logical-processor user, system and nice ticks. At each endpoint it also reads user and system time for the matrix process tree, including BLAS threads. The local .NET runner hosts the coordinator and all worker services in one process. Its only children during this batch are the V2 executor's Python processes and their descendants. The generator is a sibling process group launched by the comparison driver. The sampler measures that group separately for the observed-load column.

The workload total combines live processes with Darwin's accumulated final counters for reaped children. A job can start and finish entirely between two samples and still contribute its CPU time. Parentage and process birth times are checked during the tree walk. A changed roll-up retries the read to avoid counting a child both live and reaped. The kernel rolls up the child's own and previously waited descendant CPU. [Darwin resource accounting](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_resource.c)

Both deltas use the same elapsed monotonic interval. One fully occupied logical processor contributes one unit. External load is `clamp(host_busy − workload_busy, 0, logical_cpu_count)`. It includes other applications, the load generator, coordinator, worker-service and sampling overhead. P records the configured BLAS limit. The sampler uses actual CPU time regardless of P.

Host ticks are quantized, and the few native reads at an endpoint occur successively. This can introduce noise, particularly in a very short final interval. A decreasing counter, an unavailable tree or an overlong interval invalidates the sample. A process that deliberately detaches and outlives the matrix process can escape descendant accounting. The V2 matrix workload uses BLAS threads and waits for its work. The counter library targets macOS.

| Option | Default | Meaning |
|---|---:|---|
| `--budget` | 10 | Configured V2 thread budget B. The driver rejects P > B before release. |
| `--interval` | 1 s | Time between sample endpoints. |
| `--window` | 3 | Consecutive valid external-load samples in the arithmetic mean. |
| `--stale` | 3 intervals | Maximum age of the snapshot used for admission. |
| `--grace` | 2 s | Continuous idle time with no pending P fitting before solo admission. |
| `--phase` | 10 s | Length of each low or high phase under changing load. |

The gate waits for a full smoothing window, with a warmup timeout of `(window + 2) × interval` seconds so unavailable telemetry cannot strand the batch. A missing, warming or stale snapshot selects B and records a reason. Sampling resumes in the background. A gap resets the smoothing window.

V3.1 sets `B_eff = clamp(B − round(smoothed_external), 1, B)`. Half units round upward (away from zero). Under V2, the same measurement and reporting run with `B_eff = B`. Each idle-worker poll selects the largest K with `P <= B_eff − U`, then the earliest arrival. U sums P over the currently Running attempts. The V2 write trigger rechecks the winner and worker inside the assignment transaction. It uses one cached reading for the check and its audit. Exiting Running releases the reservation once. The coordinator's existing 20 ms scheduling cycle rechecks idle workers even without a completion.

A drop below U leaves all current attempts running. With B = 10, U = 6 and external = 3, a P = 1 task fits and a P = 4 task waits. If the entire batch is idle and all pending tasks stay too large for the grace period, the highest-ranked valid task starts alone. Its solo reservation blocks further assignments until it ends, including through a budget recovery. The grace period restarts after each such job.

## Load conditions and timing

Each arm uses a fresh database, workers and load group. Burners are prepared before warmup and start from the monotonic timestamp published at the coordinator's gate release. They check that timestamp on their next wakeup. Closing the driver's pipe stops and reaps them after each arm.

- **Quiet** starts no generator.
- **Steady** starts three single-process CPU loops at release, requesting three busy units.
- **Changing** alternates zero and four busy loops. With the default phase the requested load is zero on [0, 10) s, four on [10, 20) s, zero on [20, 30) s, and repeats. Both arms use the same schedule relative to their own release.

Each condition starts its odd pairs with V2 and its even pairs with V3.1. Makespan starts at gate release and ends at the last successful completion receipt on the coordinator's monotonic clock. Setup, calibration, warmup and result export are outside that interval.

## Reading the results

Every invocation creates a separate directory under `experiments/scheduling_v31/results/`.

- `manifest.json` and `calibration.json` are the frozen inputs. Each arm verifies the manifest SHA-256. Run JSONs retain the V2 event ledger and completion records, the CPU samples and the effective budget, fallback reason and solo flag at each committed assignment.
- `*-tasks.csv` contains V2's fixed-work fields, verified BLAS P, checksum, worker and timings. Export replays the ranking and reservations and verifies every task and checksum before including a pair.
- `*-cpu.csv` gives elapsed seconds, host, workload and generator busy units, raw and smoothed external load, effective budget, fallback reason, reserved threads and active workers. CPU rates average the interval ending at that row. Requested generator load is the target at the endpoint, so a row crossing a phase boundary can have a different interval average. Negative elapsed times are warmup. The final sample includes the completion report's short tail.
- `runs.csv` breaks down changed admissions into (1) committed assignments choosing a different task from fixed B in the same pending/reserved state and (2) observed idle-worker polls where fixed B had a candidate and the adaptive rule deferred. Repeated denials at the same reservation-ledger position count once across workers. The raw JSON lists these deferrals. The count measures local decisions along the observed trajectory. The file also reports overrides and the number of assignments using fallback telemetry.
- `pairs.csv` gives order, both makespans, seconds saved (`fixed − adaptive`), signed percentage change (`100 × (adaptive − fixed) / fixed`), and changed admissions. A negative percentage is faster. Every validated pair stays in the results, including regressions and exact ties. `summary.json` reports the median paired change and outcome counts per condition.
