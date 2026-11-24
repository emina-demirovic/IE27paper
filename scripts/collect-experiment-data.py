#!/usr/bin/env python3
"""Collect matched IE27 workload measurements through the existing Coordinator API."""

import argparse
import csv
import json
import random
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPOSITORY = Path(__file__).resolve().parents[1]
ENTRY_POINT = "src/Worker/Scripts/run_experiment.py"
WORKLOADS = (
    ("random-forest", "wine", 30, "classical_ml.py"),
    ("random-forest", "wine", 150, "classical_ml.py"),
    ("q-learning-discrete", "cartpole", 5000, "rl_workloads.py"),
    ("q-learning-discrete", "cartpole", 25000, "rl_workloads.py"),
    ("numeric-matmul", "matrix-192", 30, "numeric_matmul.py"),
    ("numeric-matmul", "matrix-384", 60, "numeric_matmul.py"),
)
TERMINAL_STATUSES = {2, 3, 4, "Completed", "Failed", "Cancelled"}


def request_json(base_url, path, payload=None):
    request = Request(
        base_url + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {error.code}: {detail}") from error


def require_host(url, host_id):
    online = [worker for worker in request_json(url, "/api/workers") if worker["isOnline"]]
    if {worker.get("hostId") for worker in online} != {host_id}:
        raise RuntimeError(f"Only workers on {host_id!r} may be online during this batch.")

    hosts = request_json(url, "/api/hosts")
    if not any(
        host["hostId"] == host_id and not host["isStale"]
        and host["sample"].get("cpuUsagePercent") is not None
        for host in hosts
    ):
        raise RuntimeError(f"No fresh CPU sample for {host_id!r}. Check the monitor and rerun.")


def analyze(commit, algorithm, environment, budget, module, seed):
    command = [
        sys.executable, str(REPOSITORY / "src/TaskAnalyzer/analyze_ast.py"),
        "--repository", str(REPOSITORY), "--commit", commit, "--entry-point", ENTRY_POINT,
        "--arg", f"algorithm={algorithm}", "--arg", f"environment={environment}",
        "--arg", f"max-steps={budget}", "--arg", f"seed={seed}",
    ]
    if algorithm == "numeric-matmul":
        command.extend(["--arg", f"matrix-size={environment.split('-')[1]}"])

    analysis = json.loads(subprocess.check_output(command))
    if f"src/Worker/Scripts/{module}" not in analysis["coverage"]["scannedFiles"]:
        raise RuntimeError(f"{module} was not analyzed at {commit}. Commit the workload and rebuild the Worker.")
    return analysis


def wait_for_attempt(url, csv_path, experiment_id, host_id, timeout):
    deadline = time.monotonic() + timeout + 30
    attempt = None
    while time.monotonic() < deadline:
        if attempt is None:
            experiment = request_json(url, f"/api/experiments/{experiment_id}")
            if experiment["status"] in TERMINAL_STATUSES:
                attempt = experiment["attempt"]
                if not attempt:
                    raise RuntimeError(f"Experiment {experiment_id} ended before assignment.")

        if attempt is not None:
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                matches = [
                    row for row in csv.DictReader(stream)
                    if row["experiment_id"] == experiment_id and row["attempt"] == str(attempt)
                ]
            if matches:
                if len(matches) != 1:
                    raise RuntimeError(f"Duplicate CSV rows for {experiment_id}, attempt {attempt}.")
                row = matches[0]
                if row["status"] != "Completed":
                    raise RuntimeError(f"{experiment_id} ended as {row['status']}: {experiment.get('resultMessage')}")
                if (
                    row["host_id"] != host_id or not row["analysis_json"]
                    or not row["execution_duration_ms"] or row["sample_stale"] != "false"
                    or not row["cpu_usage_percent"]
                ):
                    raise RuntimeError(f"Incomplete or mismatched CSV row for {experiment_id}, attempt {attempt}.")
                return row

        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {experiment_id} in {csv_path}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5031")
    parser.add_argument("--csv", type=Path, help="Path written by the local Coordinator")
    parser.add_argument("--host-id", help="HostId of the computer being measured")
    parser.add_argument("--commit", default="HEAD", help="Git source revision shared with the Worker")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per execution")
    parser.add_argument("--dry-run", action="store_true", help="Analyze all specifications without submitting")
    args = parser.parse_args()
    if args.rounds < 1 or not 1 <= args.timeout <= 86400:
        parser.error("--rounds must be positive and --timeout must be between 1 and 86400")
    if not args.dry_run and (not args.csv or not args.host_id):
        parser.error("--csv and --host-id are required for collection")

    try:
        commit = subprocess.check_output([
            "git", "-C", str(REPOSITORY), "rev-parse", "--verify", "--end-of-options",
            f"{args.commit}^{{commit}}",
        ], text=True).strip()
        specs = []
        for algorithm, environment, budget, module in WORKLOADS:
            specs.append({
                "name": f"Dataset {algorithm} {environment} {budget}",
                "algorithm": algorithm,
                "environment": environment,
                "seed": args.seed,
                "maxSteps": budget,
                "timeoutSeconds": args.timeout,
                "taskAnalysis": analyze(commit, algorithm, environment, budget, module, args.seed),
            })

        if args.dry_run:
            print(json.dumps({"expectedAttempts": len(specs) * args.rounds, "specifications": specs}, indent=2))
            return

        if not args.csv.is_file():
            raise RuntimeError(f"CSV missing: {args.csv}. Start the Coordinator with ExperimentCsvPath first.")

        url = args.url.rstrip("/")
        generator = random.Random(args.seed)
        for round_number in range(1, args.rounds + 1):
            order = generator.sample(specs, len(specs))
            for spec in order:
                require_host(url, args.host_id)
                payload = {**spec, "name": f"{spec['name']} (round {round_number})"}
                experiment = request_json(url, "/api/experiments", payload)
                experiment_id = experiment["id"]
                print(f"Submitted {payload['name']}: {experiment_id}", flush=True)
                row = wait_for_attempt(url, args.csv, experiment_id, args.host_id, args.timeout)
                print(f"  Attempt {row['attempt']}: {row['execution_duration_ms']} ms", flush=True)
        print(f"Confirmed {args.rounds * len(specs)} completed experiments in {args.csv}.")
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
