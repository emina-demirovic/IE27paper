#!/usr/bin/env python3
"""Run the IE27 CSV pilot with an isolated Coordinator and one macOS Worker."""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY = Path(__file__).resolve().parents[2]
ENTRY_POINT = "src/Worker/Scripts/run_experiment.py"
WORKER_ID = "mac-pilot"
HOST_ID = "ie27-mac"
SEEDS = (42, 43)


def request_json(url, payload=None):
    request = Request(
        url,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def wait_for(description, read, ready, processes, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f"Probni proces se završio sa kodom {process.returncode}.")
        try:
            result = read()
            if ready(result):
                return result
        except HTTPError:
            raise
        except (URLError, FileNotFoundError, TimeoutError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Isteklo vreme za: {description}.")


def start_app(dotnet, project, output_directory, *arguments):
    project_directory = REPOSITORY / "src" / project
    assembly = project_directory / "bin" / "Debug" / "net10.0" / f"{project}.dll"
    with (output_directory / f"{project.lower()}.log").open("w", encoding="utf-8") as log:
        return subprocess.Popen(
            [dotnet, str(assembly), *arguments],
            cwd=project_directory,
            stdout=log,
            stderr=subprocess.STDOUT,
        )


def submit_experiment(url, seed):
    parameters = {"algorithm": "simulated-workload", "environment": "local", "seed": seed,
                  "maxSteps": 100}
    analysis = subprocess.check_output(
        [
            sys.executable, str(REPOSITORY / "src/TaskAnalyzer/analyze_ast.py"),
            "--repository", str(REPOSITORY), "--commit", "HEAD", "--entry-point", ENTRY_POINT,
            "--arg", f"algorithm={parameters['algorithm']}",
            "--arg", f"environment={parameters['environment']}",
            "--arg", f"seed={seed}", "--arg", f"max-steps={parameters['maxSteps']}",
        ],
        text=True,
    )
    response = request_json(f"{url}/api/experiments", {
        **parameters, "name": f"CSV pilot - seed {seed}", "taskAnalysis": json.loads(analysis),
    })
    return response["id"]


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def verify_rows(rows, submitted):
    if len(rows) != len(submitted) or {row["experiment_id"] for row in rows} != set(submitted):
        raise RuntimeError("CSV nema tačno jedan red za svaki poslati eksperiment.")

    for row in rows:
        seed = submitted[row["experiment_id"]]
        if (
            row["attempt"] != "1" or row["status"] != "Completed" or
            row["seed"] != str(seed) or row["host_id"] != HOST_ID or
            row["sample_stale"] != "false" or not row["cpu_usage_percent"] or
            not (row["execution_duration_ms"].isdigit() and int(row["execution_duration_ms"]) > 0) or
            not row["analysis_json"] or row["entry_point"] != ENTRY_POINT
        ):
            raise RuntimeError(f"Neočekivan CSV red za seed {seed}: {row['status']}.")
        print(f"Seed {seed}: {row['status']}, {row['execution_duration_ms']} ms", flush=True)


def run_pilot(dotnet, port, directory):
    url = f"http://127.0.0.1:{port}"
    csv_path = directory / "attempts.csv"
    processes = []

    try:
        for project in ("Coordinator", "Worker"):
            subprocess.run(
                [dotnet, "build", str(REPOSITORY / "src" / project / f"{project}.csproj")],
                cwd=REPOSITORY,
                check=True,
            )

        processes.append(start_app(
            dotnet, "Coordinator", directory,
            "--urls", url,
            f"--Coordinator:DatabasePath={directory / 'coordinator.db'}",
            f"--Coordinator:ExperimentCsvPath={csv_path}",
            "--Raft:ClientCommandReplicationEnabled=false",
        ))
        wait_for(
            "Coordinator i zaglavlje CSV-a",
            lambda: (request_json(f"{url}/api/workers"), csv_path.is_file()),
            lambda result: result[1],
            processes,
        )

        processes.append(start_app(
            dotnet, "Worker", directory,
            f"--Worker:Id={WORKER_ID}", f"--Worker:HostId={HOST_ID}",
            f"--Worker:CoordinatorBaseUrl={url}", "--Worker:ResourceMonitor:Enabled=true",
            "--Worker:Executor:Mode=Process", f"--Worker:Executor:PythonCommand={sys.executable}",
        ))
        wait_for(
            "svež CPU uzorak",
            lambda: request_json(f"{url}/api/hosts"),
            lambda hosts: any(
                host["hostId"] == HOST_ID and not host["isStale"] and
                host["sample"].get("cpuUsagePercent") is not None for host in hosts
            ),
            processes,
        )

        submitted = {}
        for seed in SEEDS:
            submitted[submit_experiment(url, seed)] = seed

        rows = wait_for(
            "CSV redovi za dva eksperimenta", lambda: read_csv(csv_path),
            lambda result: len(result) >= len(SEEDS), processes, timeout=60,
        )
        verify_rows(rows, submitted)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    print(f"CSV sa dva proverena reda: {csv_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5042, help="Coordinator port (default: 5042)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    dotnet = shutil.which("dotnet")
    if dotnet is None and os.access("/usr/local/share/dotnet/dotnet", os.X_OK):
        dotnet = "/usr/local/share/dotnet/dotnet"
    if dotnet is None:
        parser.error("Potreban je .NET 10 SDK.")

    directory = Path(tempfile.mkdtemp(prefix="ie27-csv-pilot-"))
    print(f"Privremeni direktorijum za CSV, bazu i logove: {directory}", flush=True)
    try:
        run_pilot(dotnet, args.port, directory)
    except KeyboardInterrupt:
        parser.exit(130, "\nPilot je zaustavljen.\n")
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Pilot nije uspeo: {error}\nProveri logove u {directory}.\n")


if __name__ == "__main__":
    main()
