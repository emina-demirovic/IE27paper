"""Run from the IE27 workspace using the system Python (psutil) and the local worker venv."""
import argparse
import csv
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import psutil

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RUNNER = REPO / "experiments/scheduling_v1_real"
PYTHON = Path.home() / "ie27-ml-env/bin/python"
DOTNET = Path(shutil.which("dotnet") or REPO.parent / ".dotnet/dotnet").resolve()
HOST = "danilo-mac"
sys.path.insert(0, str(REPO / "src/ML"))
import runtime_predictor as predictor

ENV = dict(os.environ, OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1", OMP_NUM_THREADS="1",
           MKL_NUM_THREADS="1", BLIS_NUM_THREADS="1", DOTNET_ROOT=str(DOTNET.parent),
           DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE="false", PYTHONDONTWRITEBYTECODE="1")


def snapshot():
    cpu = psutil.cpu_percent(interval=.2)
    mem = psutil.virtual_memory()
    return dict(hostId=HOST, isStale=False, sample=dict(cpuUsagePercent=cpu,
                totalMemoryBytes=mem.total, memoryKind="free", memoryBytes=mem.free))


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def measure(spec, token):
    host = snapshot()["sample"]
    cmd = [str(PYTHON), str(REPO / "src/Worker/Scripts/run_experiment.py"), "--experiment-id", token,
           "--algorithm", spec["algorithm"], "--environment", spec["environment"], "--seed", str(spec["seed"]),
           "--max-steps", str(spec["maxSteps"])]
    from attempt_history import record
    started = datetime.now(timezone.utc).isoformat()
    row = dict(experiment_id=token, attempt=1, status="Completed", host_id=HOST, execution_duration_ms=None,
               analysis_json=json.dumps(spec["taskAnalysis"], separators=(",", ":")), algorithm=spec["algorithm"],
               max_steps=spec["maxSteps"], total_memory_bytes=host["totalMemoryBytes"], memory_kind="free",
               memory_bytes=host["memoryBytes"], cpu_usage_percent=host["cpuUsagePercent"], sample_stale="false")
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=ENV, check=True, timeout=120)
        row["execution_duration_ms"] = (time.perf_counter() - start) * 1000
        metrics = [json.loads(line.removeprefix("RESULT_JSON:")) for line in proc.stdout.splitlines()
                   if line.startswith("RESULT_JSON:")]
        if len(metrics) != 1:
            raise ValueError("Missing workload result")
    except BaseException:
        row.update(status="Failed", execution_duration_ms=(time.perf_counter()-start)*1000)
        raise
    finally:
        record([dict(row, experiment_id=uuid.uuid4().hex, task_id=token, policy="solo",
                     source="reference" if token.startswith("heldout-") else "calibration",
                     environment=spec["environment"], seed=spec["seed"], dispatched_at_utc=started,
                     finished_at_utc=datetime.now(timezone.utc).isoformat())])
    return row, metrics[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--subset", action="store_true", help="Run only Random Forest and NumPy")
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--copies", type=int, default=6)
    parser.add_argument("--reuse", type=Path, help="Use the frozen training set and predictions of a completed run")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    specs = json.loads(subprocess.check_output([sys.executable, str(REPO / "scripts/collect-experiment-data.py"),
                       "--commit", "af23ff5", "--rounds", "1", "--dry-run"]))["specifications"]
    if args.subset:
        specs = [s for s in specs if s["algorithm"] != "q-learning-discrete"]
    if args.reuse:
        old = args.reuse
        forecasts = json.loads((old / "predictions.json").read_text())["configurations"]
        keys = ["algorithm", "environment", "maxSteps"]
        if [[s[k] for k in keys] for s in specs] != [[f[k] for k in keys] for f in forecasts]:
            raise ValueError("Calibration configurations do not match this workload")
        for filename in ("training.csv", "predictions.json"):
            shutil.copyfile(old / filename, out / filename)
        earlier = json.loads((old / "r1-FIFO.json").read_text())["rows"]
        references = {int(row["Name"].split("-")[1]):row["metrics"] for row in earlier}
    else:
        history, references = [], {}
        for rnd in range(3):
            order = list(enumerate(specs))
            random.Random(8200 + rnd).shuffle(order)
            for i, spec in order:
                row, metrics = measure(spec, f"cal-{rnd}-{i}")
                if i in references and references[i] != metrics:
                    raise ValueError(f"Calibration output changed for {i}")
                references[i] = metrics
                history.append(row)
            print("Calibration round", rnd + 1, flush=True)
        with (out / "training.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, history[0]); w.writeheader(); w.writerows(history)
        host = snapshot()
        model = predictor.RuntimePredictor(predictor.load_observations([out / "training.csv"]), neighbors=3)
        forecasts = [predictor.predict_candidates(model, s["taskAnalysis"], [host])[0] for s in specs]
        save(out / "predictions.json", dict(host=host, configurations=[dict(algorithm=s["algorithm"],
             environment=s["environment"], maxSteps=s["maxSteps"], calibrationMs=[r["execution_duration_ms"]
             for r in history if r["algorithm"] == s["algorithm"] and r["max_steps"] == s["maxSteps"]],
             **p) for s, p in zip(specs, forecasts)]))
    print("Predictions (ms):", [p["predictedDurationMs"] for p in forecasts], flush=True)
    summary = []
    for rnd in range(1, args.pairs + 1):
        jobs = []
        expected = {}
        for i, (spec, forecast) in enumerate(zip(specs, forecasts)):
            for j in range(args.copies):
                name = f"config-{i}-copy-{j:02}"
                expected[name] = references[i]
                jobs.append(dict(Id=name, K=forecast["predictedDurationMs"], Algorithm=spec["algorithm"],
                    Environment=spec["environment"], MaxSteps=spec["maxSteps"], Seed=spec["seed"]))
        seed = 2700 + rnd
        random.Random(seed).shuffle(jobs)
        for idx, job in enumerate(jobs):
            job["ArrivalIndex"] = idx
        manifest = out / f"r{rnd}-manifest.json"
        save(manifest, jobs)
        times = {}
        for policy in (["FIFO", "LPT"] if rnd % 2 else ["LPT", "FIFO"]):
            dest = out / f"r{rnd}-{policy}.json"
            subprocess.run([str(DOTNET), str(RUNNER / "bin/Debug/net10.0/SchedulingV1.dll"), str(manifest),
                            policy, str(dest), str(PYTHON)], cwd=RUNNER, env=ENV, check=True, timeout=210)
            run = json.loads(dest.read_text())
            if run["workers"] != 10 or len(run["rows"]) != len(jobs):
                raise ValueError("Unexpected number of workers/jobs")
            for task in run["rows"]:
                if task["metrics"] != expected[task["Name"]]:
                    raise ValueError(f"Wrong result for {task['Name']}")
            times[policy] = run["makespan"]
            print(f"Pair {rnd} {policy} {times[policy]:.3f}s", flush=True)
        saved = times["FIFO"] - times["LPT"]
        summary.append(dict(pair=rnd, shuffle_seed=seed, first=next(iter(times)), jobs=len(jobs),
                   fifo_s=times["FIFO"], v1_s=times["LPT"], saved_s=saved, reduction_pct=100*saved/times["FIFO"]))
        with (out / "pairs.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, summary[0]); w.writeheader(); w.writerows(summary)
    print("Median paired reduction:", statistics.median(r["reduction_pct"] for r in summary), flush=True)


if __name__ == "__main__":
    main()
