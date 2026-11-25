"""Paired runs on the unchanged bytes of one saved V2 session."""
import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parent / "scheduling_v2"
sys.path.insert(0, str(V2))
from calibration import make_manifest, save_json
from experiment import export, preflight, verify_checksums, write_csv

FIXED, ADAPTIVE = "LPT-KP", "CPU-LPT-KP"
CONDITIONS = ("quiet", "steady", "changing")


@contextmanager
def background(condition, gate, phase):
    if condition == "quiet":
        yield 0
        return
    cmd = [sys.executable, HERE / "load.py", condition, gate, str(phase)]
    with subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          text=True) as proc:
        try:
            if proc.stdout.readline().strip() != "ready":
                raise RuntimeError("Background group failed to start")
            yield proc.pid
            if proc.poll() is not None:
                raise RuntimeError("Background group exited during the run")
        finally:
            proc.stdin.close()
            try:
                code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise
            if code:
                # Also stop burners if the supervisor died before its finally block.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                raise RuntimeError(f"Background group exited with status {code}")


def inputs(args, directory):
    source = args.v2_session
    if source is None:
        candidates = sorted((V2 / "results").glob(f"*-{args.command}-*/manifest.json"))
        if not candidates:
            raise ValueError("Supply --v2-session pointing to a saved V2 session.")
        source = candidates[-1].parent
    for name in ("manifest.json", "calibration.json"):
        shutil.copyfile(source / name, directory / name)
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    calibration_bytes = (directory / "calibration.json").read_bytes()
    cal = json.loads(calibration_bytes)
    if (args.command != cal["mode"] or
            manifest != make_manifest(cal, hashlib.sha256(calibration_bytes).hexdigest())):
        raise ValueError("Manifest differs from the V2 workload for this calibration and mode.")
    if any(j["p"] > args.budget for j in manifest["jobs"]):
        raise ValueError("Manifest contains P > B; no run started.")
    preflight(cal)
    print("Frozen V2 inputs:", source, flush=True)
    return manifest, hashlib.sha256(path.read_bytes()).hexdigest()


def requested(t, condition, phase):
    if t < 0 or condition == "quiet":
        return 0
    if condition == "steady":
        return 3
    return 4 * (int(t / phase) % 2)


def timeseries(raw, path):
    cpu = raw["cpu"]
    opt = cpu["options"]
    events = iter(raw["events"])
    event = next(events, None)
    reserved = active = 0
    rows = []
    prev = None
    for sample in cpu["samples"]:
        t = sample["elapsed_s"]
        points = []
        if prev and prev["fallback"] is None and prev["elapsed_s"] + opt["stale"] < t:
            points.append(dict.fromkeys(sample) | dict(elapsed_s=prev["elapsed_s"] + opt["stale"],
                               effective_budget=raw["budget"], fallback="stale"))
        points.append(sample)
        for point in points:
            end = point["elapsed_s"]
            while event and event["time_s"] <= end:
                reserved += event["delta"]
                active += 1 if event["delta"] > 0 else -1
                event = next(events, None)
            rows.append(dict(**point, reserved_threads=reserved, active_workers=active,
                             requested_generator=requested(end, opt["condition"], opt["phase"])))
        prev = sample
    write_csv(path, rows)


def run(args):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = HERE / "results" / f"{stamp}-{args.command}-{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True)
    print("Results:", directory, flush=True)
    manifest, digest = inputs(args, directory)
    runs, pairs = [], []
    reference = None
    for condition in CONDITIONS if args.condition == "all" else (args.condition,):
        for rep in range(1, args.repeats + 1):
            order = (FIXED, ADAPTIVE) if rep % 2 else (ADAPTIVE, FIXED)
            pair = {}
            for policy in order:
                run_id = f"{condition}-r{rep:02}-{policy}"
                print("Starting", run_id, flush=True)
                out = directory / f"{run_id}.json"
                with tempfile.TemporaryDirectory() as temp:
                    gate = Path(temp) / "release"
                    with background(condition, gate, args.phase) as pid:
                        options = dict(interval=args.interval, window=args.window, stale=args.stale,
                                       grace=args.grace, condition=condition, phase=args.phase,
                                       load_pid=pid, gate=str(gate), logical_cpus=os.sysconf("SC_NPROCESSORS_ONLN"))
                        config = Path(temp) / "options.json"
                        save_json(config, options)
                        subprocess.run(["dotnet", "bin/Debug/net10.0/SchedulingV2.dll", directory / "manifest.json",
                                        digest, policy, out, str(args.budget), str(args.in_process),
                                        sys.executable, config], cwd=V2, check=True)
                raw = json.loads(out.read_bytes())
                summary, checksums = export(raw, manifest, run_id, directory)
                if reference is None:
                    reference = checksums
                verify_checksums(reference, checksums)
                timeseries(raw, directory / f"{run_id}-cpu.csv")
                pair[policy] = summary
                runs.append(dict(condition=condition, repeat=rep,
                                 transport="TestServer" if args.in_process else "Kestrel", **summary))
                write_csv(directory / "runs.csv", runs)
            fixed, adaptive = (pair[p]["makespan_s"] for p in (FIXED, ADAPTIVE))
            saved = fixed - adaptive
            row = dict(condition=condition, repeat=rep, first_policy=order[0], manifest_id=digest,
                       fixed_s=fixed, adaptive_s=adaptive, saved_s=saved, change_pct=-100*saved/fixed,
                       changed_admissions=pair[ADAPTIVE]["changed_admissions"],
                       outcome="tie" if saved == 0 else ("faster" if saved > 0 else "slower"))
            pairs.append(row)
            write_csv(directory / "pairs.csv", pairs)
            print(f"{condition} pair {rep}: {fixed:.4f}s fixed, {adaptive:.4f}s adaptive, "
                  f"{saved:+.4f}s saved, {row['changed_admissions']} changed decisions.", flush=True)
    summary = {}
    for condition in dict.fromkeys(row["condition"] for row in pairs):
        group = [row for row in pairs if row["condition"] == condition]
        summary[condition] = dict(pairs=len(group), median_paired_change_pct=statistics.median(
            row["change_pct"] for row in group), outcomes={outcome: sum(row["outcome"] == outcome for row in group)
                                                         for outcome in ("faster", "slower", "tie")})
    save_json(directory / "summary.json", dict(manifest_id=digest, conditions=summary))


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("command", choices=("smoke", "full"))
    cli.add_argument("--v2-session", type=Path, help="directory containing a saved V2 manifest and calibration")
    cli.add_argument("--condition", choices=(*CONDITIONS, "all"), default="all")
    cli.add_argument("--repeats", type=int)
    cli.add_argument("--budget", type=int, default=10)
    cli.add_argument("--interval", type=float, default=1.)
    cli.add_argument("--window", type=int, default=3)
    cli.add_argument("--stale", type=float, help="maximum sample age in seconds (default 3 intervals)")
    cli.add_argument("--grace", type=float, default=2.)
    cli.add_argument("--phase", type=float, default=10., help="seconds per changing-load phase")
    cli.add_argument("--in-process", action="store_true")
    args = cli.parse_args()
    if args.repeats is None:
        args.repeats = 1 if args.command == "smoke" else 3
    if args.stale is None:
        args.stale = 3 * args.interval
    if (min(args.repeats, args.window, args.budget) < 1 or
            not all(math.isfinite(v) for v in (args.interval, args.stale, args.phase, args.grace)) or
            args.interval < .01 or args.stale <= args.interval or args.grace < 0 or args.phase <= 0):
        cli.error("Check positive counts, interval >= 0.01s, stale > interval, grace >= 0 and phase > 0.")
    run(args)


if __name__ == "__main__":
    main()
