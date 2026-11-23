# Scheduling V2 · fixed-work matrix jobs

V2 compares how long the same batch takes on one Mac with ten workers. LPT-K
takes the largest pending one-thread reference time K. LPT-KP takes the largest
K whose requested BLAS thread limit P fits the remaining budget (B defaults to
10). Both break ties by arrival index. All ten registered workers stay alive,
including workers waiting for an eligible job.

## Run from the repository root

Use Bash, Python 3.11 and the .NET 10 SDK. The launcher also recognizes this
workspace's SDK in `../.dotnet`. Setup creates a private Python environment and
checks the native BLAS limit at 1, 2, and 4 threads.

```bash
bash experiments/scheduling_v2/run.sh setup
bash experiments/scheduling_v2/run.sh test
bash experiments/scheduling_v2/run.sh smoke --repeats 2
bash experiments/scheduling_v2/run.sh calibrate
bash experiments/scheduling_v2/run.sh control --repeats 1
bash experiments/scheduling_v2/run.sh full --repeats 3
```

The runner starts the real coordinator and ten instances of the repository's
WorkerService on loopback HTTP. Each assignment launches a separate Python
process through PythonProcessExperimentExecutor. For a restricted environment
append `--in-process` to smoke, control, or full. This changes coordinator HTTP
transport to ASP.NET TestServer. The Python processes and GEMMs are identical.
Use the same transport and calibration for the comparisons you report.
V1 remains available through `bash experiments/scheduling_v1/run.sh smoke`.

### BLAS environment

Setup pins the Python 3.11 NumPy 1.26.4 wheel and threadpoolctl. Each job checks
NumPy's build metadata against the loaded BLAS pool, sets its limit inside the
process, and queries it before and after the timed multiplications. A NumPy
built with Apple Accelerate cannot use this threadpoolctl path to verify
arbitrary numeric limits. An unsupported environment fails with the setup
command. [NumPy wheel build](https://github.com/numpy/numpy/blob/v1.26.4/tools/wheels/cibw_before_build.sh)
and [threadpoolctl](https://github.com/joblib/threadpoolctl).

There is also an offline option for this Mac. In the same Terminal, set these
two variables **instead of running setup**, then use the other commands above.

```bash
export SCHED_V2_PYTHON="$HOME/ie27-ml-env/bin/python"
export SCHED_V2_OPENBLAS="/Applications/Julia-1.11.app/Contents/Resources/julia/lib/julia/libopenblas64_.dylib"
```

The default operation is one `np.matmul(A, B, out=C)` per iteration. With an
explicit OpenBLAS library, the job calls that library's row-major
`cblas_dgemm` directly on the same three contiguous NumPy float64 buffers.
This path uses OpenBLAS's native thread-limit setter and getter. The results
identify the library, version/configuration, entry point and NumPy version.
Changing the environment after calibration requires a matching frozen
calibration. P describes configured capacity. V2 does not sample CPU use.

### Calibration and manifest

Calibration starts one child at a time. It probes N = 768, 1536, 2304 at P = 1,
2, 4 using the same seeded matrices and R across P. Ten sets of matrix buffers
must fit within a quarter of physical RAM. The printed requirement is
3 × N² × 8 bytes per job, plus separate process and BLAS overhead.

Each full calibration point has three samples per P. A child warms BLAS with
one extra GEMM and times exactly R more. A separate fresh child executes the
normal job with no warmup, measuring end-to-end time from Python launch through
exit. Calibration records raw samples, median compute time, median time per
GEMM, median end-to-end time and one-thread-relative speedup. Nominal class
targets are 0.75, 3 and 8 seconds at P=1. The selector looks for at least 1.05×
speedup at P=2 or 4 when choosing a larger candidate for medium/long jobs. It
remeasures the selected (N,R), adjusting R up to twice if outside the requested
range. K is the actually measured median one-thread compute time for the final
(N,R). The printed values show the achieved reference times and speedups.

Calibration writes `experiments/scheduling_v2/results/calibration.json` once.
For a new calibration, pass a new `--calibration PATH` to calibrate and then the
same path to control/full. Relative paths resolve from the V2 directory.
Smoke uses a separate small calibration with two samples per P and 18 real
jobs. To run a short real P=1 control, pass a smoke session's calibration file
to `control --calibration PATH`.

| Class | P=1 | P=2 | P=4 |
|---|---:|---:|---:|
| Short | 60 | 15 | 5 |
| Medium | 5 | 10 | 10 |
| Long | 0 | 3 | 7 |

Full/control use the frozen class definitions, seed 2702, stable logical IDs,
per-task matrix seeds and one shuffled arrival order. Control changes only P
to 1. Every job generates A and B once, reuses A, B and C for exactly R GEMMs,
and returns the trace of C as its checksum. A session copies its calibration
and writes one manifest before launching either policy. Every run checks
the SHA-256 of the same manifest bytes. Override the budget with `--budget B`.
P above B is rejected before dispatch under either policy.

### Admission and timing

The shared V1/V2 harness verifies every expected task is pending and all ten
workers are online before the coordinator opens the gate. V2 installs its SQL
view and triggers only in that run's temporary SQLite database. The standard
assignment command changes a row from Pending to Running. In that same write
transaction the guard rechecks the highest eligible task, the worker and the
remaining budget. Each Running row contributes its P exactly once. Any exit
from Running releases it, including failure, completed cancellation or requeue.
A cancellation request alone keeps the reservation. Rejected or rolled-back
updates leave no capacity change or audit event.

Makespan uses the shared monotonic coordinator clock, from gate release to
receipt of the final accepted successful completion. It includes worker polling,
process startup, matrix allocation, GEMMs and reporting. The SQLite reservation
ledger timestamps each status transition on the same clock. The fraction over
budget integrates the intervals with sum(P) > B, clipped to the measured batch.
Peak sum(P) and this fraction describe reserved limits rather than measured
CPU utilization.

### Outputs and interpretation

Each session has its own directory under `experiments/scheduling_v2/results/`.

- `manifest.json` and `calibration.json` reproduce the exact jobs and K values.
- Each run JSON contains the ordered reservation ledger, completion receipts,
  and worker results. Its task CSV gives worker, N, R, seed, K, P, verified P,
  dispatch/completion seconds, process time, compute time, checksum and status.
- `runs.csv` records makespan, peak reserved P, fraction over B (0–1), completed
  count, jobs per minute and transport. `pairs.csv` records policy order and
  seconds saved = LPT-K − LPT-KP. Percentage reduction is 100 × seconds
  saved / LPT-K. Negative values are regressions. Zero is a measured tie.
  `summary.json` reports the median of the individual paired reductions.
- The first policy alternates on successive pairs. Only validated runs enter
  the comparison. Export independently replays eligibility and tie-breaking
  against each dispatch, checks the assignment and release for every attempt,
  verifies worker occupancy, status and exact work, and compares every checksum
  across runs (relative tolerance 1e−10, absolute tolerance 1e−8).

The deterministic test replays identical availability with all 115 P values
set to 1. It checks both policies against an independent expected order.
Other tests exercise competing SQLite connections, a largest job that does
not fit, rollbacks, failed/cancelled/requeued attempts, checksum failures and
lost or duplicate tasks. Smoke timings include interpreter startup and are for
verification. Use the full paired results to answer the research question.
