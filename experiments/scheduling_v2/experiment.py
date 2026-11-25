"""Calibrate, freeze a workload, and compare paired runs on the local platform."""
import argparse
import csv
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from calibration import ROOT, calibrate, make_manifest, save_json, signature


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def export(raw, manifest, run_id, directory):
    jobs = {j["task_id"]: j for j in manifest["jobs"]}
    batch = raw["tasks"]
    if len(batch) != len(jobs) or {t["task_id"] for t in batch} != jobs.keys():
        raise ValueError("Missing or duplicate task")
    pending = dict(jobs)
    by_id = {t["task_id"]: t for t in batch}
    makespan = max(t["completion_s"] for t in batch)
    reserved = peak = 0
    over = last = 0.
    active = {}
    dispatch = {}
    cpu = raw.get("cpu")
    decisions = {row["seq"]: row for row in cpu["dispatch"]} if cpu else {}
    changed = overrides = 0
    solo_worker = None
    for seq, e in enumerate(raw["events"], 1):
        task, worker, delta = e["task_id"], e["worker_id"], e["delta"]
        t = e["time_s"]
        if t < last or worker not in raw["workers"] or abs(delta) != jobs[task]["p"] or e["attempt"] != 1:
            raise ValueError(f"Invalid reservation event {e}")
        if reserved > raw["budget"]:
            over += min(t, makespan) - min(last, makespan)
        if delta > 0:
            if worker in active or task in dispatch or t > by_id[task]["completion_s"]:
                raise ValueError(f"Duplicate/overlapping assignment: {e}")
            budget = raw["budget"]
            ranked = sorted(pending.values(), key=lambda j: (-j["k"], j["arrival_index"]))
            if cpu:
                info = decisions.pop(seq)
                budget = info["effective"]
                if (not 1 <= budget <= raw["budget"] or solo_worker is not None or
                        ((info["fallback"] or raw["policy"] == "LPT-KP") and budget != raw["budget"])):
                    raise ValueError(f"Invalid CPU admission at {task}")
                if info["solo"]:
                    if reserved or any(j["p"] <= budget for j in ranked):
                        raise ValueError(f"Unnecessary progress override at {task}")
                    overrides += 1
                    solo_worker = worker
                    budget = raw["budget"]
                fixed = next(j for j in ranked if j["p"] <= raw["budget"] - reserved)
                changed += fixed["task_id"] != task
            expected = next((j for j in ranked if raw["policy"] == "LPT-K"
                             or j["p"] <= budget - reserved), None)
            if expected is None or task != expected["task_id"]:
                raise ValueError(f"Incorrect dispatch order or admission at {task}")
            del pending[task]
            dispatch[task] = t
            active[worker] = task
        elif active.pop(worker, None) != task or by_id[task]["worker_id"] != worker:
            raise ValueError(f"Unmatched release: {e}")
        if delta < 0 and worker == solo_worker:
            solo_worker = None
        last = t
        reserved += delta
        peak = max(peak, reserved)
    if decisions or active or reserved or len(dispatch) != len(jobs):
        raise ValueError("Reservation ledger did not balance")
    if raw["policy"] != "LPT-K" and peak > raw["budget"]:
        raise ValueError("Admission exceeded budget")

    common = dict(policy=raw["policy"], run_id=run_id, manifest_id=raw["manifest_id"])
    rows, checksums = [], {}
    for task, start in dispatch.items():
        j, t = jobs[task], by_id[task]
        m = t["metrics"] or {}
        rows.append(dict(**common, **j, worker_id=t["worker_id"], experiment_id=t["experiment_id"],
                         attempt=t["attempt"], dispatch_s=start, completion_s=t["completion_s"],
                         status=t["status"], process_ms=t["process_ms"], compute_s=m.get("compute_s"),
                         backend=m.get("backend"), library=m.get("library"), operation=m.get("operation"),
                         verified_p=m.get("verified_p"), checksum=m.get("checksum")))
    write_csv(directory / f"{run_id}-tasks.csv", rows)
    for row in rows:
        task = row["task_id"]
        t, j = by_id[task], jobs[task]
        if t["status"] != "Completed" or t["attempt"] != 1:
            raise ValueError(f"{task} {t['status']}: {t['result_message']}")
        m = t["metrics"]
        if (signature(m) != manifest["backend"] or m["verified_p"] != j["p"] or
                m["requested_p"] != j["p"] or m["warmup_s"] != 0 or
                any(m[k] != j[k] for k in ("seed", "n", "r")) or not math.isfinite(m["checksum"])):
            raise ValueError(f"{task} backend, limit, checksum, or fixed work differs from manifest")
        checksums[task] = m["checksum"]
    if cpu:
        common.update(changed_admissions=changed + len(cpu["deferred"]), different_task=changed,
                      deferred_decisions=len(cpu["deferred"]), progress_overrides=overrides,
                      fallback_dispatches=sum(d["fallback"] is not None for d in cpu["dispatch"]))
    return dict(**common, makespan_s=makespan, budget=raw["budget"], peak_reserved_p=peak,
                fraction_over_budget=over/makespan, completed_tasks=len(checksums),
                tasks_per_minute=60*len(checksums)/makespan), checksums


def verify_checksums(reference, actual):
    if reference.keys() != actual.keys() or any(
            not math.isclose(reference[t], actual[t], rel_tol=1e-10, abs_tol=1e-8) for t in reference):
        raise ValueError("Paired tasks produced different checksums or task IDs")


def preflight(calibration):
    # Catch an environment change before releasing a long benchmark.
    for p in (1, 2, 4):
        cmd = [sys.executable, str(ROOT / "matrix_job.py"), "--algorithm", "numpy-dgemm",
               "--environment", f"64:{p}", "--max-steps", "1", "--seed", "0"]
        m = json.loads(subprocess.check_output(cmd, text=True).removeprefix("RESULT_JSON:"))
        if signature(m) != calibration["backend"] or m["verified_p"] != p:
            raise ValueError("BLAS runtime differs from frozen calibration; select its environment or recalibrate.")


def compare(args):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session = f"{now}-{args.command}-{uuid.uuid4().hex[:10]}"
    directory = ROOT / "results" / session
    directory.mkdir(parents=True)
    print("Results:", directory, flush=True)
    frozen = directory / "calibration.json"
    if args.command == "smoke":
        calibrate(frozen, smoke=True)
    else:
        if not args.calibration.exists():
            raise ValueError("Run bash experiments/scheduling_v2/run.sh calibrate first.")
        shutil.copyfile(args.calibration, frozen)
    calibration = json.loads(frozen.read_bytes())
    if args.command == "full" and calibration["mode"] != "full":
        raise ValueError("A full run requires full-duration calibration.")
    manifest = make_manifest(calibration, hashlib.sha256(frozen.read_bytes()).hexdigest(), args.command == "control")
    manifest_file = directory / "manifest.json"
    digest = save_json(manifest_file, manifest)
    if any(j["p"] > args.budget for j in manifest["jobs"]):
        raise ValueError("Manifest contains P > B. No dispatch has been released.")

    preflight(calibration)
    run_rows, pairs = [], []
    gold = None
    for rep in range(1, args.repeats+1):
        policies = ("LPT-K", "LPT-KP") if rep % 2 else ("LPT-KP", "LPT-K")
        times = {}
        for policy in policies:
            run_id = f"{session}-r{rep:02}-{policy}"
            print("Starting", run_id, flush=True)
            out = directory / f"{run_id}.json"
            subprocess.run(["dotnet", "bin/Debug/net10.0/SchedulingV2.dll", str(manifest_file), digest,
                            policy, str(out), str(args.budget), str(args.in_process), sys.executable], check=True)
            raw = json.loads(out.read_bytes())
            summary, checksums = export(raw, manifest, run_id, directory)
            if gold is None:
                gold = checksums
            verify_checksums(gold, checksums)
            times[policy] = summary["makespan_s"]
            run_rows.append(dict(repeat=rep, transport="TestServer" if args.in_process else "Kestrel", **summary))
            write_csv(directory / "runs.csv", run_rows)
        saved = times["LPT-K"] - times["LPT-KP"]
        pct = 100 * saved / times["LPT-K"]
        pairs.append(dict(repeat=rep, manifest_id=digest, first_policy=policies[0],
                          lpt_k_s=times["LPT-K"], lpt_kp_s=times["LPT-KP"], saved_s=saved,
                          reduction_pct=pct, outcome="tie" if saved == 0 else ("faster" if saved > 0 else "slower")))
        write_csv(directory / "pairs.csv", pairs)
        print(f"Pair {rep}: LPT-K {times['LPT-K']:.4f}s, LPT-KP {times['LPT-KP']:.4f}s, "
              f"saved {saved:+.4f}s ({pct:+.3f}%).", flush=True)
    median = statistics.median(row["reduction_pct"] for row in pairs)
    save_json(directory / "summary.json", dict(manifest_id=digest, pairs=len(pairs), median_paired_reduction_pct=median))
    print(f"Median paired makespan reduction: {median:+.3f}%")


def main():
    cli = argparse.ArgumentParser()
    subs = cli.add_subparsers(dest="command", required=True)
    for name in ("calibrate", "smoke", "full", "control"):
        sub = subs.add_parser(name)
        if name != "smoke":
            sub.add_argument("--calibration", type=Path, default=ROOT / "results/calibration.json")
        if name != "calibrate":
            sub.add_argument("--repeats", type=int, default=1 if name == "smoke" else 3)
            sub.add_argument("--budget", type=int, default=10)
            sub.add_argument("--in-process", action="store_true")
    args = cli.parse_args()
    if args.command == "calibrate":
        calibrate(args.calibration)
    elif args.repeats < 1 or args.budget < 1:
        cli.error("Budget and repeats must be positive")
    else:
        compare(args)


if __name__ == "__main__":
    main()
