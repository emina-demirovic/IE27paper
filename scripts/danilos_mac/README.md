# Run the classical ML batch on one Mac

Run one coordinator and one or more worker processes on the same computer. No second computer is needed. All scripts in this folder use `http://localhost:5031` by default, so Wi-Fi IP changes do not affect the local experiment.

These are adapted copies of the scripts in Danilo's `IE27` directory. The originals remain unchanged. Use this folder's launchers together: the originals may use a LAN IP instead of localhost. The copies resolve repository paths independently of the current Terminal directory.

## What each script does

| Script | Purpose |
| --- | --- |
| `run-coordinator.command` | Builds and starts the coordinator on localhost port 5031. Stores tasks and results in the coordinator's configured SQLite database. |
| `run-mac-worker.sh` | Builds and starts one worker. Optional arguments: worker ID, coordinator URL. Defaults to `mac-w1`. |
| `run-mac-workers.sh` | Takes a worker count, builds once, and starts that many workers with unique IDs. Optional second argument: coordinator URL. Saves separate logs and stops its workers on Ctrl+C. |
| `submit-ml-batch.py` | Submits five rounds of the four real ML tasks by default. Checks for online workers first and saves the submitted task IDs. |
| `check-ml-time.py` | Reads the saved IDs, reports completion and worker counts, saves results, and calculates total batch time. `--wait` polls until completion or a 30-minute wait limit. |
| `mac-env.sh` | Shared launcher setup. Finds the repository and uses the existing sibling `.dotnet` installation when available; otherwise uses `dotnet` on PATH. Do not run separately. |

## 1. Prepare the Mac once

You need Python 3 and the .NET 10 SDK. Danilo's existing `IE27/.dotnet` installation is detected automatically. For another Mac, install .NET 10 and make `dotnet` available in Terminal.

Run these commands one at a time. If the environment is already prepared, skip this step.

```bash
python3 -m venv "$HOME/ie27-ml-env"
"$HOME/ie27-ml-env/bin/python" -m pip install scikit-learn certifi
export SSL_CERT_FILE="$("$HOME/ie27-ml-env/bin/python" -m certifi)"
"$HOME/ie27-ml-env/bin/python" -c "from sklearn.datasets import fetch_california_housing; data = fetch_california_housing(); print('Ready:', data.data.shape)"
```

The last command should print `Ready: (20640, 8)`. It downloads California Housing before the timed experiments. Workers read the cached dataset without downloading it. The other three datasets are bundled with scikit-learn. Worker launchers set the certificate path themselves.

## 2. Start the coordinator — Terminal tab 1

Open the repository directory (adjust this path if your clone is elsewhere):

```bash
cd "$HOME/Desktop/IE27/IE27paper"
bash scripts/danilos_mac/run-coordinator.command
```

Keep this tab open. Confirm the startup message says `Now listening on: http://localhost:5031`. Stop any older coordinator using that port first.

## 3. Start workers — Terminal tab 2

For a baseline with exactly one worker:

```bash
cd "$HOME/Desktop/IE27/IE27paper"
bash scripts/danilos_mac/run-mac-workers.sh 1
```

For four workers, use `4` instead of `1`. Keep this tab open. Do not leave the one-worker launcher running when measuring four workers, or you will have five workers.

Alternatively, start a single worker with visible console logs:

```bash
bash scripts/danilos_mac/run-mac-worker.sh mac-w1
```

Wait for registration before submitting. Check workers at <http://localhost:5031/api/workers>; the intended workers should have `isOnline: true`. Multi-worker logs are under `scripts/danilos_mac/worker-logs/<run-id>/worker-1.log`, etc.

## 4. Submit and measure — Terminal tab 3

```bash
cd "$HOME/Desktop/IE27/IE27paper"
python3 scripts/danilos_mac/submit-ml-batch.py
python3 scripts/danilos_mac/check-ml-time.py --wait
```

The default batch matches `scripts/submit-classical-ml.ps1`: five repetitions of Iris, Wine, Breast Cancer, and California Housing; algorithm `random-forest`; seed 42; 50 trees; timeout 300 seconds per task. The first three tasks use classification accuracy; California Housing uses regression RMSE. The runner uses an 80/20 train/test split and `n_jobs=1` for each model.

No separate JSON configuration file is required. To change the workload:

```bash
python3 scripts/danilos_mac/submit-ml-batch.py --rounds 5 --trees 100
```

To inspect requests without submitting:

```bash
python3 scripts/danilos_mac/submit-ml-batch.py --dry-run
```

Each submission saves its own batch file in `scripts/danilos_mac/ml-batches/`. The checker defaults to the latest batch. For an earlier batch, pass its file explicitly:

```bash
python3 scripts/danilos_mac/check-ml-time.py scripts/danilos_mac/ml-batches/BATCH_TIMESTAMP.json --wait
```

Replace `BATCH_TIMESTAMP.json` with the actual filename printed during submission. Results are saved alongside it as `BATCH_TIMESTAMP-results.json`. These files and worker logs are excluded from Git. You can also inspect all tasks at <http://localhost:5031/api/experiments>.

## 5. Compare one worker with four workers

1. Finish any earlier queued jobs before measuring a fresh batch.
2. Start exactly one worker and wait until it is online.
3. Submit a batch, wait for all 20 tasks to succeed, and record its batch filename and total time.
4. Stop that worker launcher with Ctrl+C. Start four workers and wait until all four are online.
5. Submit the same workload again and record its batch filename and total time.
6. Repeat each configuration several times under similar computer load. Keep tree count, seeds, package versions, and dataset cache the same. Record any warm-up runs separately.

Total batch time is **latest `finishedAtUtc` minus earliest `createdAtUtc`** among the batch's tasks, matching the PowerShell calculation. It includes submission, queueing, scheduling, Python startup, data loading, training, and result reporting. It is not pure model training time and is not the sum of individual task durations. Time is printed only when the entire batch succeeds.

Compute speedup as `one-worker batch time / four-worker batch time`. Four workers share one computer's CPU and memory; four times the speed is not guaranteed. Paper comparisons require matching workload, hardware, software versions, and timing definition. A batch submitted before workers were available includes that waiting delay and should not be used as a clean benchmark.

## Troubleshooting and stopping

- **No online workers:** make sure coordinator, workers, and submitter use the same URL. Do not mix these localhost scripts with older scripts pointing to a LAN address.
- **HTTP 204 for the next task:** normal; no task is assigned to that worker yet. HTTP 200 for a heartbeat means the coordinator recognizes the worker.
- **Failed tasks:** inspect `resultMessage` in the results JSON and worker logs. Ensure scikit-learn is installed in `ie27-ml-env` and California Housing was downloaded using that environment.
- **After pulling new code:** stop and restart workers so the launchers rebuild and copy the latest Python runner.
- **Interrupted submission:** IDs received so far are saved. Do not blindly resubmit: a request that timed out might still have created a task. Inspect the coordinator first.
- **Stop workers:** Ctrl+C in their launcher tab. Stop the coordinator with Ctrl+C in its tab. Ctrl+C in the result checker stops waiting only; it does not cancel tasks.

For a deliberately remote coordinator, pass its URL consistently to the worker and submitter, for example `bash scripts/danilos_mac/run-mac-workers.sh 4 http://HOST:5031` and `python3 scripts/danilos_mac/submit-ml-batch.py --url http://HOST:5031`. Remote access also requires the coordinator to listen on a reachable interface; the included coordinator launcher intentionally binds to localhost for the one-computer procedure.
