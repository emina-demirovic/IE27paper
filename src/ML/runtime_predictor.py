"""Train and evaluate a first per-host Python runtime predictor from IE27 CSVs."""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


DISPATCHER = "src/Worker/Scripts/run_experiment.py"
DISPATCH_TARGETS = {
    "random-forest": "src/Worker/Scripts/classical_ml.py",
    "numeric-matmul": "src/Worker/Scripts/numeric_matmul.py",
    "q-learning-control": "src/Worker/Scripts/rl_workloads.py",
    "q-learning-discrete": "src/Worker/Scripts/rl_workloads.py",
}
LIBRARIES = ("numpy", "scipy", "pandas", "sklearn", "gymnasium")
AST_COUNTS = ("forCount", "whileCount", "callCount")
OPERATORS = ("add", "subtract", "multiply", "matrixMultiply", "divide", "power")
TELEMETRY = ("cpu_percent", "ram_available_fraction", "ram_free_fraction")


@dataclass
class Observation:
    program: str
    host: str
    features: dict
    duration_ms: float


def nonnegative_number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def sum_counts(files, field):
    counts = [nonnegative_number(file_features.get(field)) for file_features in files]
    return sum(counts) if counts and None not in counts else None


def task_features(analysis, algorithm=None, max_steps=None):
    features = analysis["features"]
    known = features.get("known", {})
    derived = features.get("derived", {})
    ast = derived.get("ast", {})
    files = [ast.get("entryPoint", {}), *ast.get("localModules", {}).values()]
    calls = list(derived.get("callsByFile", {}).values())
    arguments = known.get("arguments", {})
    algorithm = algorithm or arguments.get("algorithm")
    if max_steps is None:
        max_steps = nonnegative_number(arguments.get("max-steps"))
    inputs = list(known.get("inputs", {}).values())
    sizes = [nonnegative_number(item.get("sizeBytes")) for item in inputs]
    shapes = [item["shape"] for item in inputs if isinstance(item.get("shape"), list)]

    result = {field: sum_counts(files, field) for field in AST_COUNTS}
    depths = [nonnegative_number(file.get("maxSyntacticLoopDepth")) for file in files]
    result["loop_depth"] = max(depths) if None not in depths else None
    for operator in OPERATORS:
        result[f"operator_{operator}"] = sum_counts(
            [file.get("arithmeticOperatorCounts", {}) for file in files], operator
        )
    for library in LIBRARIES:
        result[f"library_{library}"] = (
            int(any(library in file.get("libraries", []) for file in calls)) if calls else None
        )

    result.update({
        "input_size_bytes": sum(sizes) if sizes and None not in sizes else None,
        "largest_array_elements": max((math.prod(shape) for shape in shapes), default=None),
        "n_estimators": max_steps if algorithm == "random-forest" else None,
        "step_budget": max_steps if algorithm in ("q-learning-control", "q-learning-discrete") else None,
        "matrix_size": nonnegative_number(arguments.get("matrix-size")),
        "repeats": max_steps if algorithm == "numeric-matmul"
            else nonnegative_number(arguments.get("repeats")),
    })
    return result


def machine_features(total, memory_kind, memory, cpu, fresh):
    total = nonnegative_number(total)
    memory = nonnegative_number(memory) if fresh else None
    cpu = nonnegative_number(cpu) if fresh else None
    fraction = memory / total if total and memory is not None and memory <= total else None
    return {
        "total_memory_bytes": total,
        "cpu_percent": cpu if cpu is not None and cpu <= 100 else None,
        "ram_available_fraction": fraction if memory_kind == "available" else None,
        "ram_free_fraction": fraction if memory_kind == "free" else None,
    }


def load_observations(paths):
    observations = []
    seen = set()

    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for line, row in enumerate(csv.DictReader(stream), start=2):
                host = row.get("host_id")
                duration = nonnegative_number(row.get("execution_duration_ms"))
                if row.get("status") != "Completed" or duration is None or not host:
                    continue
                if not row.get("analysis_json"):
                    continue

                try:
                    analysis = json.loads(row["analysis_json"])
                    if analysis.get("schemaVersion") != 1:
                        raise ValueError("unsupported analysis schemaVersion")
                    program = analysis["task"]["entryPoint"]
                    algorithm = row.get("algorithm")
                    if algorithm == "simulated-workload":
                        continue
                    if program == DISPATCHER:
                        program = DISPATCH_TARGETS.get(algorithm)
                        if program is None:
                            continue  # Other dispatcher branches are simulated workloads.

                    key = (row["experiment_id"], row["attempt"])
                    if key in seen:
                        continue
                    task = task_features(analysis, algorithm, nonnegative_number(row.get("max_steps")))
                    machine = machine_features(
                        row.get("total_memory_bytes"), row.get("memory_kind"), row.get("memory_bytes"),
                        row.get("cpu_usage_percent"), row.get("sample_stale") == "false",
                    )
                except (KeyError, ValueError, TypeError, AttributeError) as error:
                    raise ValueError(f"{path}:{line}: invalid dataset entry ({error})") from error

                seen.add(key)
                observations.append(Observation(program, host, {**task, **machine}, duration))

    if not observations:
        raise ValueError("No completed real workloads with task analysis and a host were found.")
    return observations


class RuntimePredictor:
    """Weighted k-nearest-neighbor regression with training scales fitted per host."""

    def __init__(self, observations, neighbors, include_telemetry=True):
        self.by_host = defaultdict(list)
        for row in observations:
            self.by_host[row.host].append(row)

        self.neighbors = neighbors
        self.scales = {}
        for host, rows in self.by_host.items():
            scales = {}
            for name in rows[0].features:
                if not include_telemetry and name in TELEMETRY:
                    continue
                values = [row.features[name] for row in rows if row.features[name] is not None]
                if values:
                    scales[name] = statistics.pstdev(values) or 1.0
            self.scales[host] = scales

    def predict(self, host, features):
        if host not in self.by_host:
            raise ValueError(f"No training measurements for host {host!r}.")

        distances = []
        for row in self.by_host[host]:
            distance = 0.0
            for name, scale in self.scales[host].items():
                expected = features[name]
                actual = row.features[name]
                if expected is None or actual is None:
                    distance += float(expected is not actual)
                else:
                    distance += min(abs(expected - actual) / scale, 4.0) ** 2
            distances.append((distance, row.duration_ms))

        nearest = sorted(distances, key=lambda pair: pair[0])[:self.neighbors]
        weights = [1 / (1 + math.sqrt(distance)) for distance, _ in nearest]
        return sum(weight * row[1] for weight, row in zip(weights, nearest)) / sum(weights)


def evaluate(observations, neighbors):
    programs = sorted({row.program for row in observations})
    if len(programs) < 3:
        raise ValueError("Evaluation requires at least three distinct program implementations.")

    errors = defaultdict(list)
    for program in programs:
        training = [row for row in observations if row.program != program]
        testing = [row for row in observations if row.program == program]
        with_telemetry = RuntimePredictor(training, neighbors)
        without_telemetry = RuntimePredictor(training, neighbors, include_telemetry=False)

        medians = {
            host: statistics.median(row.duration_ms for row in rows)
            for host, rows in with_telemetry.by_host.items()
        }
        for row in testing:
            if row.host not in medians:
                raise ValueError(f"Host {row.host!r} has no training rows when holding out {program!r}.")
            estimates = {
                "host_median": medians[row.host],
                "knn_without_telemetry": without_telemetry.predict(row.host, row.features),
                "knn_with_telemetry": with_telemetry.predict(row.host, row.features),
            }
            for name, estimate in estimates.items():
                errors[name].append(abs(estimate - row.duration_ms))

    return {
        "attemptCount": len(observations),
        "programCount": len(programs),
        "split": "leave_one_program_out",
        "maeMs": {name: statistics.mean(values) for name, values in errors.items()},
    }


def predict_candidates(model, analysis, hosts):
    if analysis.get("schemaVersion") != 1:
        raise ValueError("Unsupported analysis schemaVersion.")
    task = task_features(analysis)
    result = []
    for host in hosts:
        sample = host.get("sample") or {}
        resource = machine_features(
            sample.get("totalMemoryBytes"), sample.get("memoryKind"), sample.get("memoryBytes"),
            sample.get("cpuUsagePercent"), host.get("isStale") is False,
        )
        host_id = host["hostId"]
        estimate = model.predict(host_id, {**task, **resource})
        result.append({
            "hostId": host_id,
            "predictedDurationMs": round(estimate, 2),
            "cpuTelemetryAvailable": resource["cpu_percent"] is not None,
            "memoryTelemetryAvailable": any(resource[name] is not None for name in TELEMETRY[1:]),
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, nargs="+", help="One or more IE27 attempts CSVs")
    parser.add_argument("--neighbors", type=int, default=3)
    parser.add_argument("--analysis", type=Path, help="Task Analyzer JSON for prediction")
    parser.add_argument("--hosts", type=Path, help="JSON array from GET /api/hosts")
    args = parser.parse_args()

    if args.neighbors < 1:
        parser.error("--neighbors must be positive")
    if bool(args.analysis) != bool(args.hosts):
        parser.error("--analysis and --hosts must be provided together")

    try:
        observations = load_observations(args.csv)
        if args.analysis:
            model = RuntimePredictor(observations, args.neighbors)
            analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
            hosts = json.loads(args.hosts.read_text(encoding="utf-8"))
            result = predict_candidates(model, analysis, hosts)
        else:
            result = evaluate(observations, args.neighbors)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"{error}\n")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
