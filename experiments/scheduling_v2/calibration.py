"""Sequential calibration and reproducible workload construction."""
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
THREADS = (1, 2, 4)
SEED = 2702
MIX = ((60, 15, 5), (5, 10, 10), (0, 3, 7))
SMOKE_MIX = ((5, 2, 2), (1, 2, 2), (0, 1, 3))
CLASSES = ("short", "medium", "long")
TARGETS = (.75, 3., 8.)


def save_json(path, obj):
    data = (json.dumps(obj, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def signature(metrics):
    return {k: metrics[k] for k in ("backend", "library", "operation", "numpy")}


def measure(n, r, samples, seed=SEED):
    """One fresh worker-equivalent process at a time. Same seed and R at every P."""
    rows = []
    for p in THREADS:
        raw = []
        for _ in range(samples):
            cmd = [sys.executable, str(ROOT / "matrix_job.py"), "--algorithm", "numpy-dgemm",
                   "--environment", f"{n}:{p}", "--max-steps", str(r), "--seed", str(seed)]
            # Warm one GEMM in the same process used for the compute reference.
            m = json.loads(subprocess.check_output([*cmd, "--warmup"], text=True).removeprefix("RESULT_JSON:"))
            # An ordinary fresh job has no warmup and executes exactly R GEMMs.
            start = time.perf_counter()
            output = subprocess.check_output(cmd, text=True)
            elapsed = time.perf_counter() - start
            cold = json.loads(output.removeprefix("RESULT_JSON:"))
            if (m["verified_p"] != p or cold["verified_p"] != p or signature(m) != signature(cold)
                    or not math.isclose(m["checksum"], cold["checksum"], rel_tol=1e-10)):
                raise ValueError(f"Calibration execution mismatch for {n=}, {r=}, {p=}")
            raw.append(dict(**m, end_to_end_s=elapsed, cold_compute_s=cold["compute_s"]))
        seconds = statistics.median(m["compute_s"] for m in raw)
        speedup = rows[0]["median_compute_s"] / seconds if rows else 1.
        e2e = statistics.median(m["end_to_end_s"] for m in raw)
        rows.append(dict(n=n, r=r, p=p, median_compute_s=seconds, median_per_gemm_s=seconds/r,
                         median_end_to_end_s=e2e, speedup=speedup, samples=raw))
        print(f"N={n} R={r} P={p}: {seconds:.5f}s compute, {seconds/r:.5f}s/GEMM, "
              f"{e2e:.4f}s end to end, {speedup:.3f}x", flush=True)
    base = rows[0]["samples"][0]
    for row in rows:
        for m in row["samples"]:
            if signature(m) != signature(base) or not math.isclose(m["checksum"], base["checksum"], rel_tol=1e-10):
                raise ValueError("Calibration backend or checksum mismatch")
    return rows


def calibrate(path, smoke=False):
    if path.exists():
        raise ValueError(f"Frozen calibration already exists at {path}. Choose a new --calibration path.")
    sizes = (128, 256, 384) if smoke else (768, 1536, 2304)
    ram = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    samples = 2 if smoke else 3
    probes = {}
    for n in sizes:
        buffers = 3*n*n*8
        print(f"N={n}: {buffers/2**20:.1f} MiB/job, {10*buffers/2**20:.1f} MiB for ten; "
              "Python and BLAS use additional memory.", flush=True)
        if 10*buffers > ram/4:
            continue
        probes[n] = measure(n, 2, samples)
    if not probes:
        raise ValueError("No candidate fits the matrix-buffer allowance of 25% of physical RAM.")
    sizes = sorted(probes)
    profiles = []
    configs = {}
    for i, name in enumerate(CLASSES):
        n = sizes[min(i, len(sizes)-1)]
        if i > 0:
            # Seek a larger candidate if the nominal size doesn't speed up.
            eligible = [s for s in sizes if s >= n and max(x["speedup"] for x in probes[s][1:]) >= 1.05]
            n = eligible[0] if eligible else sizes[-1]
        per_gemm = probes[n][0]["median_per_gemm_s"]
        r = i+2 if smoke else max(1, round(TARGETS[i]/per_gemm))
        for attempt in range(3):
            rows = measure(n, r, samples)
            profiles.extend(rows)
            k = rows[0]["median_compute_s"]
            if smoke or (.5, 2, 6)[i] <= k <= (1, 4, 10)[i] or attempt == 2:
                break
            r = max(1, round(r * TARGETS[i]/k))
        configs[name] = dict(n=n, r=r, k=k)
        print(f"{name}: N={n}, R={r}, frozen K={k:.6f}s; speedup at P=2/4: "
              f"{rows[1]['speedup']:.2f}x / {rows[2]['speedup']:.2f}x", flush=True)
    measured = [row for group in probes.values() for row in group] + profiles
    if not any(row["speedup"] > 1 for row in measured if row["p"] > 1):
        print("No tested multithreaded configuration was faster than its one-thread reference.")
    elif not any(row["speedup"] >= 1.05 for row in measured if row["p"] > 1):
        print("No tested configuration reached the 1.05x useful-speedup threshold.")
    base = measured[0]["samples"][0]
    if any(signature(row["samples"][0]) != signature(base) for row in measured):
        raise ValueError("Backend changed during calibration")
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, dict(mode="smoke" if smoke else "full", backend=signature(base), host=platform.node(),
                         machine=platform.machine(), seed=SEED, physical_ram=ram, profiles=measured, classes=configs))
    print("Frozen calibration:", path, flush=True)


def make_manifest(calibration, calibration_id, control=False):
    rng = random.Random(SEED)
    jobs = []
    mix = SMOKE_MIX if calibration["mode"] == "smoke" else MIX
    for name, counts in zip(CLASSES, mix):
        for p, count in zip(THREADS, counts):
            for _ in range(count):
                jobs.append(dict(task_id=f"matrix-{len(jobs)+1:03}", workload_class=name,
                                 seed=rng.randrange(2**31), p=1 if control else p, **calibration["classes"][name]))
    rng.shuffle(jobs)
    for i, job in enumerate(jobs):
        job["arrival_index"] = i
    return dict(seed=SEED, calibration_id=calibration_id, control=control,
                backend=calibration["backend"], jobs=jobs)
