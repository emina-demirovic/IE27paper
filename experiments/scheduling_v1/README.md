# Scheduling V1

This is a dispatch-order experiment with known durations. Ten instances of the platform's
`WorkerService` register with the real coordinator, poll their assignments, execute one
task at a time, and POST completion. The runner hosts the services in one process on
one machine. By default requests go over loopback HTTP through Kestrel on an ephemeral
port. Each policy run gets a fresh temporary SQLite database and ten fresh workers.
The launcher starts and stops them. Use Bash and the .NET 10 SDK (the existing Mac
launcher also recognizes the SDK installed in `../.dotnet` beside the repository).

From the repository root, run the smoke check or the full experiment with three
paired repetitions per scenario.

```sh
bash experiments/scheduling_v1/run.sh smoke
bash experiments/scheduling_v1/run.sh full --repeats 3
```

For environments that cannot bind a loopback port, append `--in-process` to either
command. This uses ASP.NET TestServer's HTTP handler with the same controllers,
scheduler, database, and workers. Use the same transport for comparisons.

## Workload and policies

Each manifest has 100 one-second tasks and 15 slow tasks of 30, 32, 34, 36, 38,
40, 42, 44, 46, 48, 50, 52, 54, 56, and 60 seconds. The logical task ID stays
the same across runs. The coordinator generates a separate experiment GUID for
each submission. K is the specified duration in seconds. The experimental executor
waits for K seconds on a full run, or K × 20 ms for smoke. All tasks have priority 1.

Scenario A uses the listed order, fast tasks first. Scenario B uses a seeded
shuffle (2701). The runner writes both manifests before starting and reuses each
in-memory sequence across policies and repeats. Arrival indices start at zero.
FIFO selects the lowest pending index. LPT selects the highest pending K and then
the lowest index. The coordinator checks each available worker every scheduling
cycle. Both its cycle delay and the worker polling delay are 20 ms in V1.

Before release, all 115 submissions must be pending on attempt zero and all ten
worker IDs must be online. After release, each idle worker can receive the next
task even while previous assignments on other workers are still running. On odd
repeats FIFO runs first in A and LPT first in B. On even repeats both orders reverse.

## Reading the measurements

Each invocation creates its own directory under `experiments/scheduling_v1/results/`.
It contains the following files.

- `arrival-A.csv` and `arrival-B.csv` record the submitted order, logical ID, and K.
- Each run CSV has one row per task in dispatch order. Times are seconds on the
  coordinator's monotonic clock, relative to opening the dispatch gate. Dispatch
  is the coordinator selecting the task for assignment. Completion is receipt at
  the coordinator's completion endpoint before request-body binding. Only accepted
  completions count. The runner checks persisted status, first attempt, and exactly
  one creation, assignment, and completion per task. It also checks dispatch order,
  ties, all ten worker IDs, per-worker non-overlap, and overlapping fast and slow
  work under LPT.
- `summary.csv` has one row per completed FIFO/LPT pair with both measured
  makespans, seconds saved (FIFO − LPT), and percentage reduction
  (100 × seconds saved / FIFO). Makespan is the latest accepted completion receipt.
  Negative savings mean FIFO finished sooner in that pair. The file also records
  the policy run first, duration scale, transport, and shuffle seed.

The runner checks Scenario A's zero-overhead schedule before starting workers:
FIFO takes 108 s and LPT takes 78 s. Real measurements include assignment, polling,
execution, and completion overhead. These costs are especially pronounced in the
scaled smoke test. Use full-duration pairs for performance comparisons.
