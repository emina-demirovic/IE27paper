"""Shared real-workload training data and frozen forecasts for scheduling series."""
from bisect import bisect_right
import csv
import fcntl
import hashlib
import io
import json
import os
import stat
import tempfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import median

from benchmark import HOST, REPO, predictor

DATASET = REPO / "benchmarks/data/attempts.csv"
BASE = ("experiment_id attempt status host_id execution_duration_ms analysis_json algorithm max_steps "
        "total_memory_bytes memory_kind memory_bytes cpu_usage_percent sample_stale").split()
CONTEXT = ("source dispatched_at_utc finished_at_utc run_id source_result manifest_sha256 pair task_id environment seed policy budget p "
           "worker_id worker_count arrival_index dispatch_index active_workers_before active_matrices_before "
           "active_forests_before duration_class fifo_block_size matrix_cap no_wait_at_99 "
           "matrix_priority_bonus_ms effective_budget sampling_interval_s smoothing_window cpu_fallback cpu_measurement cpu_sample_age_s "
           "predicted_ms dispatch_s completion_s").split()


def atomic_write(path, write):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", newline="",
                                     delete=False) as stream:
        temp = Path(stream.name)
        try:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            if path.exists():
                temp.chmod(stat.S_IMODE(path.stat().st_mode))
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def record(rows, dataset=None):
    """A cached arm can be imported repeatedly. Serialize writers across benchmark processes."""
    dataset = dataset or DATASET
    dataset.parent.mkdir(parents=True, exist_ok=True)
    with dataset.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fields = BASE + CONTEXT
        old = []
        if dataset.exists():
            with dataset.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                fields += [key for key in reader.fieldnames if key not in fields]
                old = list(reader)
        existing = {(r["experiment_id"], r["attempt"]): r for r in old}
        changed = False
        added = []
        for row in rows:
            key = (row["experiment_id"], str(row["attempt"]))
            prior = existing.get(key)
            if prior is None:
                existing[key] = row
                added.append(row)
            else:
                for field, value in row.items():
                    if prior.get(field) in (None, "") and value not in (None, ""):
                        prior[field] = value
                        changed = True
                if row.get("cpu_usage_percent") is not None and row.get("sample_stale") == "false" and prior.get("sample_stale") == "true":
                    prior["sample_stale"] = "false"
                    changed = True
        for r in old:
            if not r.get("source"):
                r.update(source="calibration", policy="solo")
                changed = True
            if r["source"] == "calibration" and not r.get("environment"):
                args = json.loads(r["analysis_json"])["features"]["known"]["arguments"]
                r.update(environment=args["environment"], seed=args["seed"], task_id=r["experiment_id"])
                changed = True
        if added or changed:
            def write(stream):
                writer = csv.DictWriter(stream, fields)
                writer.writeheader()
                writer.writerows(old)
                writer.writerows(added)
            atomic_write(dataset, write)
        return len(added)


@lru_cache(maxsize=None)
def analysis_json(algorithm, environment, steps, seed):
    from expanded_calibration import collector, COMMIT
    modules = {"numeric-matmul": "numeric_matmul.py", "random-forest": "classical_ml.py",
               "q-learning-discrete": "rl_workloads.py"}
    return json.dumps(collector.analyze(COMMIT, algorithm, environment, steps, modules[algorithm], seed),
                      separators=(",", ":"))


def scheduling_rows(raw, jobs, result, pair):
    job_by_name = {j["TaskId"]: j for j in jobs}
    # Older files have no UUID. Reservation timestamps distinguish actual executions
    # and are stable if an existing result is copied or replayed.
    run_id = raw.get("runId") or hashlib.sha256(json.dumps(raw["events"], sort_keys=True).encode()).hexdigest()
    config = raw.get("cpu") or {}
    bands = {d["Seq"]: d for d in config.get("band_dispatch") or []}
    audit = {d["Seq"]: d for d in config.get("dispatch", [])}
    completed = {(r["Name"], r.get("Attempt", 1)): r for r in raw["rows"]}
    finished = {(e["Task"], e["Attempt"]): e.get("Utc") for e in raw["events"] if e["Delta"] < 0}
    timed_samples = config.get("samples", [])
    sample_times = [s["elapsed_s"] for s in timed_samples]
    active = {}
    index = 0
    for seq, e in enumerate(raw["events"], 1):
        name, worker, attempt = e["Task"], e["Worker"], e["Attempt"]
        if e["Delta"] < 0:
            active.pop(worker)
            continue
        j = job_by_name[name]
        r = completed.get((name, attempt), {})
        alg, env, steps, seed = j["Algorithm"], j["Environment"], j["MaxSteps"], j["Seed"]
        sample = bands.get(seq, {})
        cpu = sample.get("HostPercent")
        decision = audit.get(seq, {})
        options = config.get("options", {})
        policy = raw["policy"]
        block = {"CpuBandsBlock10": 10, "CpuBandsBlock20Matrix": 20}.get(policy)
        origin = raw.get("startTicks")
        elapsed = (e["Ticks"]-origin)/raw["ticksPerSecond"] if origin is not None else None
        age = ((e["Ticks"] - sample["SampleTicks"]) / raw["ticksPerSecond"]
               if "SampleTicks" in sample and "ticksPerSecond" in raw else None)
        measurement = "band_average" if cpu is not None else None
        if not bands and timed_samples and elapsed is not None and decision.get("Fallback") is None:
            index_before = bisect_right(sample_times, elapsed)-1
            if index_before >= 0:
                sample = timed_samples[index_before]
                age = elapsed-sample_times[index_before]
                if sample.get("HostBusy") is not None and age <= options["Stale"] and sample.get("Fallback") is None:
                    cpu = max(0, min(100, 100*sample["HostBusy"]/config["logical_cpus"]))
                    measurement = "latest_host_sample"
        yield dict(
            source=raw.get("source", "scheduling"), dispatched_at_utc=e.get("Utc"), finished_at_utc=finished.get((name, attempt)),
            experiment_id=f"{run_id}/{name}", attempt=attempt, run_id=run_id,
            status=r.get("Status", "Completed" if r else "Interrupted"), host_id=HOST,
            source_result=str(result), manifest_sha256=raw["manifestHash"], pair=pair,
            task_id=name, algorithm=alg, environment=env, max_steps=steps, seed=seed,
            analysis_json=analysis_json(alg, env, steps, seed), policy=policy, budget=raw["budget"], p=j["P"],
            worker_id=worker, worker_count=len(raw["workers"]), arrival_index=j["ArrivalIndex"],
            dispatch_index=index, active_workers_before=len(active),
            active_matrices_before=sum(a=="numeric-matmul" for a in active.values()),
            active_forests_before=sum(a=="random-forest" for a in active.values()), duration_class=j.get("Group"),
            fifo_block_size=block, matrix_cap=raw.get("matrixCap"), no_wait_at_99=int(raw.get("noWaitAt99", False)),
            matrix_priority_bonus_ms=raw.get("matrixPriorityBonusMs", 0) if alg=="numeric-matmul" and
                (env, steps) in (("matrix-1536",945),("matrix-1600",900)) else 0,
            effective_budget=decision.get("Effective", raw["budget"] if not config else None),
            sampling_interval_s=options.get("Interval"), smoothing_window=options.get("Window"),
            cpu_usage_percent=cpu, sample_stale="false" if cpu is not None else "true",
            cpu_fallback=decision.get("Fallback"), cpu_measurement=measurement, cpu_sample_age_s=age, predicted_ms=j["K"],
            dispatch_s=elapsed,
            completion_s=r.get("completion"), execution_duration_ms=r.get("ExecutionDurationMs"))
        active[worker] = alg
        index += 1


def freeze(path, solo, budget, dataset=None):
    """One snapshot per series and budget, shared by both arms and all repetitions."""
    dataset = dataset or DATASET
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            return json.loads(path.read_text())["configurations"]
        # The CSV is atomically replaced. Hash and parse the same open version.
        with dataset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            stream.seek(0)
            rows = list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")))
        observations = []
        for row in rows:
            if row.get("source") != "calibration" or row["status"] != "Completed":
                continue
            analysis = json.loads(row["analysis_json"])
            task = predictor.task_features(analysis, row["algorithm"], int(row["max_steps"]))
            host = predictor.machine_features(row["total_memory_bytes"], row["memory_kind"], row["memory_bytes"],
                                              row["cpu_usage_percent"], row["sample_stale"] == "false")
            observations.append(predictor.Observation(row["algorithm"], row["host_id"], {**task, **host},
                                                      float(row["execution_duration_ms"])))
        model = predictor.RuntimePredictor(observations, neighbors=3)
        groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for r in rows:
            if (r.get("source") != "scheduling" or r["status"] != "Completed" or r["host_id"] != HOST
                    or r["budget"] != str(budget) or r["p"] != "1" or r["worker_count"] != "10"):
                continue
            if not r["execution_duration_ms"] or float(r["execution_duration_ms"]) <= 0:
                continue
            cfg = (r["algorithm"], r["environment"], int(r["max_steps"]), int(r["seed"]))
            variant = (r["policy"], r["matrix_cap"], r["no_wait_at_99"], r["matrix_priority_bonus_ms"])
            groups[cfg][variant][r["run_id"]].append(float(r["execution_duration_ms"]))
        forecasts = []
        for c in solo["configurations"]:
            analysis = json.loads(analysis_json(c["algorithm"], c["environment"], c["maxSteps"], c["seed"]))
            base = predictor.predict_candidates(model, analysis, [solo["host"]])[0]["predictedDurationMs"]
            variants = groups[(c["algorithm"], c["environment"], c["maxSteps"], c["seed"])]
            # Equal weight per run, then per policy variant. Each benchmark arm
            # receives identical K, before its dispatch-time load can be known.
            estimates = [median(median(times) for times in runs.values()) for runs in variants.values()]
            n = sum(len(runs) for runs in variants.values())
            # Use the solo kNN estimate as one prior run; an isolated timing
            # cannot replace all previous evidence on its own.
            estimate = (base + n * median(estimates)) / (1 + n) if n else base
            forecasts.append(dict(c, solo_predicted_ms=base, history_runs=n, predicted_ms=round(estimate, 2)))
        snapshot = dict(dataset_sha256=digest, dataset_rows=len(rows), budget=budget, p=1,
                        method="per-run and per-policy medians, shrunk toward solo kNN with one prior run", configurations=forecasts)
        atomic_write(path, lambda f: json.dump(snapshot, f, indent=2))
        return forecasts


def recover_interrupted(directory, result, dataset=None):
    """Recover committed dispatches even when no normal arm report was produced."""
    import sqlite3
    meta = json.loads((directory / "run.json").read_text())
    db_path = directory / "attempts.db"
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "v2_events" not in tables:
            return 0
        events = [dict(r) for r in db.execute(
            "SELECT task AS Task, worker AS Worker, attempt AS Attempt, ticks AS Ticks, delta AS Delta, utc AS Utc "
            "FROM v2_events ORDER BY seq")]
        if not events:
            return 0
        statuses = ["Requeued", "Running", "Completed", "Failed", "Cancelled"]
        outcomes = [dict(Name=r["task"], Attempt=r["attempt"], Status=statuses[r["status"]],
                         ExecutionDurationMs=r["duration_ms"]) for r in db.execute("SELECT * FROM v2_outcomes")]
        bands = ([dict(Seq=r["seq"], HostPercent=r["host_percent"]) for r in db.execute("SELECT * FROM band_dispatch")]
                 if "band_dispatch" in tables else [])
        dispatch = ([dict(Seq=r["seq"], Fallback=r["fallback"], Effective=r["effective"])
                     for r in db.execute("SELECT * FROM v31_dispatch")] if "v31_dispatch" in tables else [])
    jobs = meta.pop("jobs")
    pair = meta.pop("pair")
    meta.update(source="scheduling-partial", events=events, rows=outcomes, cpu=dict(band_dispatch=bands, dispatch=dispatch,
                                                       options=meta.pop("options")))
    return record(scheduling_rows(meta, jobs, result, pair), dataset)
