"""Compare fixed-budget FIFO with CPU-adaptive V3.1 on the expanded CartPole workload."""
import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import uuid
from datetime import datetime, timezone

import attempt_history as history
import subprocess
import sys

from benchmark import DOTNET, ENV, PYTHON, ROOT, save
from expanded_calibration import WITH_CARTPOLE
from expanded_pairs import manifest, read, write_table

RUNNER = ROOT
DLL = RUNNER / "bin/Debug/net10.0/RealV31.dll"


def matrix_config(job):
    return (job["Environment"], job["MaxSteps"])


def family_candidate(pending, family, active, long_configs):
    candidates = [j for j in pending if j["Algorithm"] == family]
    if family != "numeric-matmul":
        return candidates[0]
    long_running = sum(j["Algorithm"] == family and matrix_config(j) in long_configs for j in active)
    if long_running < 2:
        return max(candidates, key=lambda j: j["K"])
    return next((j for j in candidates if matrix_config(j) not in long_configs), candidates[0])


def band_target(load, no_wait_at_99=False):
    if load is None or (load >= 99 and not no_wait_at_99):
        return None
    if load < 60:
        return "long"
    return "medium" if load < 87.5 else "short"


def band_waits(raw, job_count, capacity):
    # Wall time, counted once even when several workers could accept a job.
    # Replay the gate only while there is queued work and spare capacity.
    start = raw["startTicks"]
    frequency = raw["ticksPerSecond"]
    expiry = round(raw["cpu"]["options"]["Stale"] * frequency)
    timeline = [(s["Ticks"], 0, s) for s in raw["cpu"]["samples"]]
    timeline.extend((e["Ticks"], seq, e) for seq, e in enumerate(raw["events"], 1))
    dispatch = {d["Seq"]: d for d in raw["cpu"]["band_dispatch"]}
    last, sample, used = start, None, 0
    active, pending = 0, job_count
    freshness = high = 0
    for tick, seq, item in sorted(timeline, key=lambda x: (x[0], x[1])):
        if tick > last and pending and active < capacity:
            if sample is None or sample["Ticks"] <= used:
                freshness += tick - last
            elif active:
                fresh_end = min(tick, sample["Ticks"] + expiry)
                duration = max(0, fresh_end - last)
                pct = sample["SmoothedHostPercent"]
                if pct is None:
                    freshness += duration
                elif pct >= 99 and not raw.get("noWaitAt99", False):
                    high += duration
                freshness += tick - last - duration
        last = max(last, tick)
        if seq == 0:
            sample = item
        else:
            active += item["Delta"]
            if item["Delta"] > 0:
                used = dispatch[seq]["SampleTicks"]
                pending -= 1
    return dict(wait_sample_s=freshness/frequency, wait_high_cpu_s=high/frequency)


def validate(raw, jobs, digest, policy, budget, references, matrix_cap=None, no_wait_at_99=False):
    if (raw["policy"], raw["budget"], raw["manifestHash"]) != (policy, budget, digest):
        raise ValueError("Saved execution does not match this manifest, policy or budget")
    if raw.get("noWaitAt99", False) != no_wait_at_99:
        raise ValueError("Saved execution used a different CPU admission threshold")
    if raw.get("matrixCap") != matrix_cap:
        raise ValueError("Saved execution used a different matrix limit")
    by_name = {j["TaskId"]: j for j in jobs}
    rows = raw["rows"]
    if len(rows) != len(jobs) or {r["Name"] for r in rows} != set(by_name):
        raise ValueError("Incomplete or duplicated results")
    expected = jobs if policy in ("FIFO", "FamilyFIFO") else sorted(jobs, key=lambda j: (-j["K"], j["ArrivalIndex"]))
    ranked_matrices = sorted((j for j in jobs if j["Algorithm"] == "numeric-matmul"),
                             key=lambda j: (-j["K"], j["ArrivalIndex"]))
    long_configs = set(list(dict.fromkeys(matrix_config(j) for j in ranked_matrices))[:2])
    bands = policy in ("CpuBands", "CpuBandsBlock10", "CpuBandsBlock20Matrix")
    block_size = {"CpuBandsBlock10": 10, "CpuBandsBlock20Matrix": 20}.get(policy)
    bonus_ms = raw.get("matrixPriorityBonusMs", 0)
    if bonus_ms != (3000 if policy == "CpuBandsBlock20Matrix" else 0):
        raise ValueError("Unexpected matrix priority bonus")
    priority_k = {j["TaskId"]: j["K"] for j in jobs}
    for j in jobs:
        if j["Algorithm"] == "numeric-matmul" and matrix_config(j) in (("matrix-1536", 945), ("matrix-1600", 900)):
            priority_k[j["TaskId"]] += bonus_ms
    plain_fifo = policy == "FIFO" and jobs[0].get("Group") is not None
    cpu = raw["cpu"]
    if plain_fifo and cpu is not None:
        raise ValueError("Expected FIFO with CPU sampling disabled")
    if bands:
        opts = raw["cpu"]["options"]
        if (opts["Interval"], opts["Window"], opts["HostOnly"], opts["Stale"]) != (0.05, 4, True, 0.25):
            raise ValueError("Unexpected CPU sampling settings")
        expected = jobs  # FIFO order for ties and exhausted classes
        samples = {}
        recent = []
        for sample in raw["cpu"]["samples"]:
            pct = sample["HostPercent"]
            recent = (recent + [pct])[-4:] if pct is not None else []
            smooth = sample["SmoothedHostPercent"]
            if (smooth is None) != (len(recent) < 4) or (
                    smooth is not None and not math.isclose(smooth, statistics.mean(recent), abs_tol=1e-9)):
                raise ValueError("Incorrect rolling host CPU average")
            samples[sample["Ticks"]] = smooth
        band_log = {d["Seq"]: d for d in raw["cpu"]["band_dispatch"]}
        last_sample = 0
    pending = list(expected)
    matrix_active = 0
    matrix_peak = 0
    audit = {} if plain_fifo else {r["Seq"]: r for r in cpu["dispatch"]}
    active = {}
    starts = 0
    peak = 0
    for seq, e in enumerate(raw["events"], 1):
        name, worker = e["Task"], e["Worker"]
        if worker not in raw["workers"] or e["Attempt"] != 1:
            raise ValueError("Unexpected worker or attempt")
        is_matrix = by_name[name]["Algorithm"] == "numeric-matmul"
        if e["Delta"] == 1:
            limit = budget if plain_fifo else audit[seq]["Effective"]
            eligible = next((j for j in pending if matrix_cap is None or matrix_active < matrix_cap
                             or j["Algorithm"] != "numeric-matmul"), None)
            if policy == "FamilyFIFO":
                eligible = family_candidate(pending, jobs[starts]["Algorithm"], (by_name[n] for n in active.values()),
                                            long_configs)
            if bands:
                record = band_log[seq]
                tick, pct = record["SampleTicks"], record["HostPercent"]
                if tick <= last_sample or tick > e["Ticks"] or tick not in samples:
                    raise ValueError("Reused or unknown CPU sample")
                expected_pct = samples[tick] if audit[seq]["Fallback"] is None else None
                if pct != expected_pct:
                    raise ValueError("CPU decision differs from its sampled load")
                target = band_target(pct, no_wait_at_99)
                if target is None and active:
                    raise ValueError("Dispatch during high or unavailable CPU while a worker was active")
                candidates = pending
                if block_size is not None:
                    candidates = [j for j in pending if j["ArrivalIndex"] // block_size == starts // block_size]
                eligible = max((j for j in candidates if j["Group"] == target),
                               key=lambda j: priority_k[j["TaskId"]], default=candidates[0])
                last_sample = tick
            if (bands or policy in ("FIFO", "FamilyFIFO")) and limit != budget:
                raise ValueError("Unexpected adaptive budget in fixed-budget run")
            if (eligible is None or eligible["TaskId"] != name or worker in active or
                    not 1 <= limit <= budget or len(active) + 1 > limit):
                raise ValueError(f"Invalid dispatch order or P=1 reservation for {name}")
            pending.remove(eligible)
            active[worker] = name
            matrix_active += is_matrix
            matrix_peak = max(matrix_peak, matrix_active)
            starts += 1
            peak = max(peak,len(active))
        else:
            if e["Delta"] != -1 or active.pop(worker, None) != name:
                raise ValueError(f"Incorrect release for {name}")
            matrix_active -= is_matrix
    if pending or active or matrix_active or starts != len(rows) or (not plain_fifo and len(audit) != starts):
        raise ValueError("Incomplete reservation ledger")
    errors = []
    for r in rows:
        name = r["Name"]
        if r["metrics"] != references[name.rsplit("-",1)[0]]["metrics"]:
            raise ValueError(f"Workload result differs for {name}")
        errors.append(abs(by_name[name]["K"] - r["ExecutionDurationMs"]) / 1000)
    usable = None if plain_fifo else sum(r["Fallback"] is None for r in audit.values())
    makespan = max(r["completion"] for r in rows)
    timing = {}
    if "startTicks" in raw:
        last_dispatch = max(e["Ticks"] for e in raw["events"] if e["Delta"] > 0)
        last_s = (last_dispatch - raw["startTicks"]) / raw["ticksPerSecond"]
        # Integrate active worker count to the last accepted completion.
        last_t = 0.0
        area = 0.0
        count = 0
        for e in raw["events"]:
            t = min(makespan, (e["Ticks"] - raw["startTicks"]) / raw["ticksPerSecond"])
            area += count * (t - last_t)
            last_t = t
            count += e["Delta"]
        timing = dict(tail_s=makespan-last_s, mean_active_workers=area/makespan)
    if bands:
        if len(band_log) != starts:
            raise ValueError("Incomplete CPU band decisions")
        timing.update(band_waits(raw, len(jobs), min(budget, len(raw["workers"]))))
    elif plain_fifo:
        timing.update(wait_sample_s=0.0, wait_high_cpu_s=0.0)  # FIFO has no CPU gate
    high_dispatches = sum(d["HostPercent"] is not None and d["HostPercent"] >= 99
                          for d in band_log.values()) if bands else None
    return dict(**timing, high_cpu_dispatches=high_dispatches, makespan_s=makespan, mae_s=statistics.mean(errors),
                dispatches=starts, valid_cpu_dispatches=usable, peak_reserved_p=peak,
                deferred_decisions=0 if plain_fifo else len(cpu["deferred"]), peak_active_matrices=matrix_peak)


def flush_pending(directory):
    """Replay a stopped runner; a surviving worker process holds the same lock."""
    with (directory / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        meta_path = directory / "run.json"
        if meta_path.exists():
            meta = read(meta_path)
            final = directory.parent / meta["result_name"]
            raw = read(final) if final.exists() else {}
            if raw.get("runId") == meta["runId"]:
                history.record(history.scheduling_rows(raw, meta["jobs"], final, meta["pair"]))
            else:
                history.recover_interrupted(directory, final)
        shutil.rmtree(directory)
        return True


def recover_series(series_root):
    for folder in {p.parent for p in series_root.glob("*/*/.*.pending")}:
        with (folder / ".run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            for directory in folder.glob(".*.pending"):
                flush_pending(directory)


def run_arm(out, path, jobs, policy, budget, refs, matrix_cap=None, no_wait_at_99=False):
    suffix = f"-m{matrix_cap}" if matrix_cap is not None else ""
    plain_fifo = policy == "FIFO" and jobs[0].get("Group") is not None
    if no_wait_at_99:
        suffix = "-no-wait-99"
    if plain_fifo:
        suffix = "-no-cpu"
    final = out / f"{path.stem}-{policy}{suffix}.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pair = int(path.stem[1:]) if re.fullmatch(r"r[0-9]+", path.stem) else None
    for directory in sorted(out.glob(f".{final.stem}-*.pending")):
        if not flush_pending(directory):
            raise RuntimeError(f"Runner still active in {directory}")
    if final.exists():
        raw = read(final)
        stats = validate(raw, jobs, digest, policy, budget, refs, matrix_cap, no_wait_at_99)
        history.record(history.scheduling_rows(raw, jobs, final, pair))
    else:
        run_id = uuid.uuid4().hex
        directory = out / f".{final.stem}-{run_id}.pending"
        directory.mkdir()
        temp = directory / "result.json"
        bands = policy.startswith("CpuBands")
        options = {} if plain_fifo else dict(Interval=0.05 if bands else 1, Window=4 if bands else 3)
        meta = dict(runId=run_id, result_name=final.name, policy=policy, pair=pair, jobs=jobs, budget=budget, matrixCap=matrix_cap,
                    noWaitAt99=no_wait_at_99, manifestHash=digest, workers=list(range(10)), options=options,
                    matrixPriorityBonusMs=3000 if policy=="CpuBandsBlock20Matrix" else 0)
        with (directory / "writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            history.atomic_write(directory / "run.json", lambda f: json.dump(meta, f))
            try:
                subprocess.run([str(DOTNET), str(DLL), str(path), policy, str(temp), str(PYTHON),
                                str(budget), str(os.sysconf("SC_NPROCESSORS_ONLN")),
                                *([str(matrix_cap)] if matrix_cap is not None else []),
                                *(["--no-cpu-sampling"] if plain_fifo else []),
                                *(["--no-wait-99"] if no_wait_at_99 else [])],
                               env=dict(ENV, IE27_RUN_ID=run_id, IE27_ATTEMPT_DB=str(directory/"attempts.db")),
                               cwd=RUNNER, check=True, timeout=1950, pass_fds=(lock.fileno(),))
                raw = read(temp)
                stats = validate(raw, jobs, digest, policy, budget, refs, matrix_cap, no_wait_at_99)
            except BaseException:
                history.recover_interrupted(directory, final)
                shutil.rmtree(directory)
                raise
            temp.replace(final)
            history.record(history.scheduling_rows(raw, jobs, final, pair))
            shutil.rmtree(directory)
    if policy == "V31" and stats["valid_cpu_dispatches"] == 0:
        print("Upozorenje: V3.1 je koristio rezervni budžet pri svakoj dodeli; CPU telemetrija nije bila dostupna.")
    return stats


def compare_matrix_cap(out, args, refs):
    pairs = []
    name = f"matrix-cap-{args.matrix_cap}-{args.pairs}"
    for i in range(1, args.pairs + 1):
        path = out / f"r{i:02}.json"
        jobs = read(path)
        baseline = {}
        for policy in ("FIFO", "V31"):
            saved = out / f"{path.stem}-{policy}.json"
            if not saved.is_file():
                raise FileNotFoundError(f"Missing baseline for {path.name}: {saved}")
            baseline[policy] = validate(read(saved), jobs, hashlib.sha256(path.read_bytes()).hexdigest(),
                                        policy, args.budget, refs)
        print(f"Par {i}/{args.pairs}: V3.1, najviše {args.matrix_cap} aktivnih matrica", flush=True)
        limited = run_arm(out, path, jobs, "V31", args.budget, refs, args.matrix_cap)
        elapsed = limited["makespan_s"]
        row = dict(pair=i, limited_s=elapsed, limited_mae_s=limited["mae_s"],
                   peak_matrices=limited["peak_active_matrices"], cpu_valid=limited["valid_cpu_dispatches"],
                   dispatches=limited["dispatches"])
        for label, stats in baseline.items():
            prefix = label.lower()
            original = stats["makespan_s"]
            row.update({f"{prefix}_s": original, f"{prefix}_mae_s": stats["mae_s"],
                        f"saved_vs_{prefix}_s": original - elapsed,
                        f"reduction_vs_{prefix}_pct": 100 * (original - elapsed) / original})
        pairs.append(row)
        write_table(out / f"{name}.csv", pairs)
        print(f"Limit {elapsed:.2f} s, V3.1 {row['v31_s']:.2f} s, FIFO {row['fifo_s']:.2f} s, "
              f"MAE {row['limited_mae_s']:.2f} s, maksimum matrica {row['peak_matrices']}", flush=True)
    for baseline_name in ("v31", "fifo"):
        change = statistics.median(r[f"reduction_vs_{baseline_name}_pct"] for r in pairs)
        print(f"Medijana uštede prema {baseline_name.upper()}: {change:+.2f}%")
    print("Rezultati:", out / f"{name}.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", help="Reuse a named series and its frozen predictions (default: new series)")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--pairs", type=int, default=2, help="Total number of paired repetitions, including saved pairs")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cpu-bands", action="store_true", help="Compare FIFO with total host CPU bands at a fixed budget (default 10)")
    mode.add_argument("--cpu-bands-block10", action="store_true",
                      help="Apply CPU bands within FIFO blocks of 10, reusing matching FIFO runs when available")
    mode.add_argument("--cpu-bands-block20-matrix", action="store_true",
                      help="Apply CPU bands within FIFO blocks of 20 with a 3 s priority bonus for the two long matrix configurations")
    mode.add_argument("--family-fifo", action="store_true", help="Compare FIFO with FIFO family slots and matrix promotion at fixed budget")
    mode.add_argument("--matrix-cap", type=int,
                        help="Compare a capped V3.1 run against both saved baselines on each frozen manifest")
    parser.add_argument("--no-wait-99", action="store_true",
                        help="Use the short-task band even at 99–100%% and compare with the original block-20 run")
    args = parser.parse_args()
    if args.series and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", args.series):
        parser.error("--series must be a simple folder name")
    if args.no_wait_99 and not args.cpu_bands_block20_matrix:
        parser.error("--no-wait-99 requires --cpu-bands-block20-matrix")
    blocked_bands = args.cpu_bands_block10 or args.cpu_bands_block20_matrix
    host_bands = args.cpu_bands or blocked_bands
    if args.budget is None:
        args.budget = 10 if host_bands else 12
    if min(args.pairs,args.budget) < 1:
        parser.error("--budget and --pairs must be positive")
    if args.matrix_cap is not None and args.matrix_cap < 1:
        parser.error("--matrix-cap must be positive")
    WITH_CARTPOLE.mkdir(exist_ok=True)
    experiment = "family-fifo" if args.family_fifo else "v31"
    if host_bands:
        experiment = "cpu-bands-block10" if args.cpu_bands_block10 else "cpu-bands"
    if args.cpu_bands_block20_matrix:
        experiment = "cpu-bands-block20-matrix"
    series_name = args.series or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    series_dir = WITH_CARTPOLE / "series" / series_name
    series_dir.mkdir(parents=True, exist_ok=True)
    recover_series(series_dir.parent)
    gated_dir = series_dir / f"{experiment}-b{args.budget}-p1"
    if args.no_wait_99:
        experiment += "-no-wait-99"
    out = series_dir / f"{experiment}-b{args.budget}-p1"
    out.mkdir(exist_ok=True)
    with (out / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, f"Test already running in {out}\n")
        with (WITH_CARTPOLE / ".calibration.lock").open("a") as calibration_lock:
            fcntl.flock(calibration_lock, fcntl.LOCK_EX)
            subprocess.run([sys.executable, "-B", str(ROOT / "expanded_calibration.py")], check=True)
        solo = read(WITH_CARTPOLE / "predictions.json")
        configs = history.freeze(series_dir / f"predictions-b{args.budget}-p1.json", solo, args.budget)
        print(f"Serija {series_name}, K iz istorije: {sum(c['history_runs'] > 0 for c in configs)}/{len(configs)} konfiguracija", flush=True)
        refs = {c["config"]:read(WITH_CARTPOLE / f"reference-{c['config']}.json") for c in configs}
        solo_mae = statistics.mean(abs(c["solo_predicted_ms"]-refs[c["config"]]["duration_ms"]) / 1000 for c in configs)
        challenger = "FamilyFIFO" if args.family_fifo else "V31"
        label = "FIFO sa prioritetom za duge matrice" if args.family_fifo else "V3.1"
        prefix = "family_fifo" if args.family_fifo else "v31"
        if args.cpu_bands:
            challenger, label, prefix = "CpuBands", "CPU po zonama", "cpu_bands"
        if args.cpu_bands_block10:
            challenger, label, prefix = "CpuBandsBlock10", "CPU po zonama u FIFO grupama od 10", "cpu_bands_block10"
        if args.cpu_bands_block20_matrix:
            challenger = "CpuBandsBlock20Matrix"
            label, prefix = "CPU grupe od 20, bonus matricama +3 s", "cpu_bands_block20_matrix"
        if args.no_wait_99:
            label += ", bez čekanja na 99%"
        groups = {c["config"]: c["group"] for c in configs}
        pairs, runs = [], []
        print("Rezultati:", out, flush=True)
        for i in range(1, args.pairs+1):
            jobs = []
            for original in manifest(configs,2700+i):
                job = dict(original)
                job["TaskId"] = job.pop("Id")
                job["P"] = 1
                if host_bands:
                    job["Group"] = groups[job["TaskId"].rsplit("-", 1)[0]]
                jobs.append(job)
            path = out / f"r{i:02}.json"
            if path.exists() and read(path) != jobs:
                raise ValueError(f"Frozen job manifest changed: {path}")
            if not path.exists():
                save(path, jobs)
            if args.matrix_cap is not None:
                for baseline in ("FIFO", "V31"):
                    run_arm(out, path, jobs, baseline, args.budget, refs)
                continue
            order = ("FIFO",challenger) if i % 2 else (challenger,"FIFO")
            fifo_source = out
            if blocked_bands:
                prior = series_dir / f"cpu-bands-b{args.budget}-p1"
                fifo_name = f"{path.stem}-FIFO-no-cpu.json"
                if not (out / fifo_name).exists() and (prior / fifo_name).is_file():
                    fifo_source = prior
            if args.no_wait_99:
                gated_file = gated_dir / f"{path.stem}-{challenger}.json"
                if gated_file.is_file():
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    gated = validate(read(gated_file), jobs, digest, challenger, args.budget, refs)
                    print(f"Par {i}/{args.pairs}: sa čekanjem na 99% (prethodno merenje)", flush=True)
                else:
                    print(f"Par {i}/{args.pairs}: merenje sa čekanjem na 99%", flush=True)
                    gated = run_arm(out, path, jobs, challenger, args.budget, refs)
            result = {}
            for policy in order:
                source = fifo_source if policy == "FIFO" else out
                note = " (prethodno merenje)" if source != out else ""
                print(f"Par {i}/{args.pairs}: {policy}{note}",flush=True)
                result[policy] = run_arm(source, path, jobs, policy, args.budget, refs,
                                         no_wait_at_99=args.no_wait_99 and policy == challenger)
                runs.append(dict(pair=i,policy=policy,**result[policy]))
                write_table(out / f"runs-{args.pairs}.csv", runs)
            fifo = result["FIFO"]["makespan_s"]
            candidate = result[challenger]["makespan_s"]
            pct = 100*(fifo-candidate)/fifo
            row = dict(pair=i,first=order[0],fifo_s=fifo,saved_s=fifo-candidate,
                       reduction_pct=pct,speedup=fifo/candidate,fifo_mae_s=result["FIFO"]["mae_s"])
            row[prefix+"_s"] = candidate
            row[prefix+"_mae_s"] = result[challenger]["mae_s"]
            if blocked_bands:
                row["fifo_from_previous_run"] = fifo_source != out
                if fifo_source != out:
                    row["first"] = "FIFO (historical)"
            if args.family_fifo or host_bands:
                for key in ("tail_s", "mean_active_workers"):
                    row["fifo_"+key] = result["FIFO"][key]
                    row[prefix+"_"+key] = result[challenger][key]
            if host_bands:
                for key in ("wait_sample_s", "wait_high_cpu_s"):
                    row[key] = result[challenger][key]
                print(f"Čekanje na CPU uzorak {row['wait_sample_s']:.2f} s, "
                      f"na pad CPU ispod 99% {row['wait_high_cpu_s']:.2f} s", flush=True)
            if blocked_bands:
                print(f"Od poslednje dodele do kraja: FIFO {row['fifo_tail_s']:.2f} s, "
                      f"CPU grupe {row[prefix+'_tail_s']:.2f} s", flush=True)
            if args.no_wait_99:
                saved = gated["makespan_s"] - candidate
                row.update(with_wait_s=gated["makespan_s"], saved_vs_wait_s=saved,
                           reduction_vs_wait_pct=100 * saved / gated["makespan_s"],
                           high_cpu_dispatches=result[challenger]["high_cpu_dispatches"])
                print(f"Sa čekanjem {gated['makespan_s']:.2f} s, bez čekanja {candidate:.2f} s, "
                      f"ušteda prema politici sa čekanjem {row['reduction_vs_wait_pct']:+.2f}%, "
                      f"dodela pri CPU ≥99%: {row['high_cpu_dispatches']}", flush=True)
            pairs.append(row)
            write_table(out / f"pairs-{args.pairs}.csv", pairs)
            print(f"FIFO {fifo:.2f} s, {label} {candidate:.2f} s, ušteda {pct:+.2f}%",flush=True)
        if args.matrix_cap is not None:
            compare_matrix_cap(out, args, refs)
            return
        summary = dict(budget=args.budget,p=1,pairs=len(pairs),jobs_per_arm=len(jobs),workers=10,
                       median_paired_reduction_pct=statistics.median(r["reduction_pct"] for r in pairs),
                       median_paired_speedup=statistics.median(r["speedup"] for r in pairs),
                       heldout_solo_mae_s=solo_mae,
                       fifo_execution_mae_s=statistics.mean(r["fifo_mae_s"] for r in pairs))
        summary[prefix+"_wins"] = sum(r["saved_s"]>0 for r in pairs)
        summary[prefix+"_execution_mae_s"] = statistics.mean(r[prefix+"_mae_s"] for r in pairs)
        summary[prefix+"_valid_cpu_dispatches"] = sum(r["valid_cpu_dispatches"] for r in runs if r["policy"]==challenger)
        summary[prefix+"_total_dispatches"] = len(pairs)*len(jobs)
        if args.no_wait_99:
            summary["median_reduction_vs_wait_pct"] = statistics.median(r["reduction_vs_wait_pct"] for r in pairs)
            print(f"Medijana uštede prema politici sa čekanjem: {summary['median_reduction_vs_wait_pct']:+.2f}%")
        save(out / f"summary-{args.pairs}.json", summary)
        print(f"Medijana uštede prema FIFO: {summary['median_paired_reduction_pct']:+.2f}%")
        print(f"MAE (sekunde): pojedinačno {solo_mae:.2f}, pod FIFO {summary['fifo_execution_mae_s']:.2f}, "
              f"pod {label}: {summary[prefix+'_execution_mae_s']:.2f}")
        print(f"{label}, validna CPU telemetrija: {summary[prefix+'_valid_cpu_dispatches']}/{summary[prefix+'_total_dispatches']}")


if __name__ == "__main__":
    main()
