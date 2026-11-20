# Time forecasting handoff · 20 November 2026

Start with [the final evaluation](lokalna_procena/REZULTATI_FAZE.md). The estimator predicts how many seconds a Python script will take on the calibration machine by inspecting its source. The distributed runs answer a different scheduling question: how long a batch takes when several workers share a Mac.

## Where to look

| Location | What you can do with it |
|---|---|
| [lokalna_procena/](lokalna_procena/) | Run and change the standalone Python estimator. Its [README](lokalna_procena/README.md) documents commands and methodology in Serbian. The [development summary](lokalna_procena/summary_e.txt) explains the motivation for V3. |
| [proceni.py](lokalna_procena/proceni.py) and [faze_model.py](lokalna_procena/faze_model.py) | Start here for inference. The CLI reads a script and calibration file. V3 follows local helper functions, estimates Python operation counts, and prices data preparation, training and prediction separately. |
| [podaci/faze/](lokalna_procena/podaci/faze/) | Saved V3 model, microbenchmarks, instrumented training measurements, frozen predictions and five wall-clock samples per test. The 41-file evaluation is at this level. [nezavisni/](lokalna_procena/podaci/faze/nezavisni/) contains the 12-file independent evaluation. The preliminary run is under proba/. |
| [Earlier ML experiments](lokalna_procena/REZULTATI_ML.md), [V2](lokalna_procena/REZULTATI_V2.md), [unknown-code benchmark](lokalna_procena/REZULTATI_NEPOZNAT.md) | Trace the baselines and inspect the 128 development scripts. V2 tested prediction with an algorithm family excluded from training. The final V3 report compares against Python loop counting for plain Python and V2 Ridge for sklearn. |
| [Batch index](ml-batches/index.csv) and [batch snapshots](ml-batches/) | Inspect 14 submission manifests and their result snapshots from **19 November**. Each pair shares a UTC filename stem. Join individual records by experiment ID. Thirteen snapshots show all 20 tasks completed. The earliest shows 20 pending tasks at capture and has no completed batch time. |
| [worker-logs/](worker-logs/) | Eight launch sessions from **19 November**, including early connection failures and the 1/2/4/8/16-worker runs. Each gzip file preserves the log text for one worker with local workspace paths and LAN coordinator addresses normalized. Use the batch index's worker run ID to find the directory, then the worker suffix to find the file. |

## Try the saved model

From the repository root, using Python 3.11 (recorded environment: 3.11.9 on an arm64 Mac):

```sh
cd time-forecasting/lokalna_procena
python3 proceni.py podaci/faze/testovi/csv_bag_85.py --baza podaci/faze/model.json
python3 proceni.py podaci/faze/testovi/csv_bag_85.py --baza podaci/faze/model.json --detalji
```

The first command should print approximately **3.021727** seconds with the included data. These coefficients refer to the original Mac. The second shows 9,800 training rows and 8,330 rows per ensemble member. Pass your script in place of the example. Prediction parses the source and may inspect a local CSV's dimensions. It can run using the standard library alone.

To run the tests and reproduce the evaluations, stay in the same folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ml.txt
python -m unittest discover -v
python demonstracija_faze.py
python provera_novih_programa.py
```

The last two commands execute benchmark scripts and rewrite calibration and results for the current machine. Use a separate checkout if you need to keep the recorded measurements for comparison. The [distributed launch instructions](../scripts/danilos_mac/README.md) cover the coordinator and workers separately.

## What the measurements support

On the 53 final scripts (five fresh processes each), V3 reduced mean absolute percentage error from **31.9% to 27.5%**. The count of tasks that actually took more than twice the predicted time fell from **13 to 2**. On the stricter subset of 12 scripts from six independently written programs, V3's error was **44.2%**, versus **28.8%** for the baseline. Keep this subset visible in future results. The 41-file set shares some structures with the preliminary series.

Batch wall time is latest finish minus earliest creation across a completed batch, in seconds. Worker execution duration is recorded per task in milliseconds. For example, the last 16-worker batch finished in 8.456 s, with median per-task execution of 1,240.5 ms. A completed one-worker batch finished in 66.302 s, with median per-task execution of 717.5 ms. This illustrates why throughput and per-task latency need separate targets. The log count in the index identifies launched processes. The assigned-worker count comes from the snapshot. Neither establishes continuously active concurrency.

To inspect the logs for the last run from this folder:

```sh
gzip -dc worker-logs/20261119-210029-6141/worker-1.log.gz | less
```

## Suggested next experiment

1. Collect 30–50 independently written workloads. Keep all variants of a program in one group, reserve entire programs for final testing, and freeze predictions before timing.
2. Compare V3 and the existing baseline on the same scripts. Break down errors in seconds, percentage errors and severe underestimates for Python and ML. Inspect unsupported while loops and opaque library calls first.
3. For scheduling, record host ID, active experiments on that host, the experiment process tree's CPU time and peak sampled memory, available host memory and thread settings. Compare identical batches under different worker counts. Today's worker records provide IDs, timings and assignment evidence; host resource telemetry is proposed future work.
