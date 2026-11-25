"""Calibrate the workload families and freeze held-out forecasts for the paired runs."""
import argparse
import csv
import importlib.util
import json
import random

from benchmark import REPO, ROOT, measure, predictor, save, snapshot

PREVIOUS = ROOT / "expanded"
WITH_CARTPOLE = ROOT / "expanded-cartpole"
COMMIT = "af23ff56c3047f1353f1b4194c1abab64c87141a"
loader = importlib.util.spec_from_file_location("collector", REPO / "scripts/collect-experiment-data.py")
collector = importlib.util.module_from_spec(loader)
loader.loader.exec_module(collector)

# Each configuration is (worker environment, step budget).
TRAIN = [
    *(("wine", n) for n in (180, 800, 1800, 5600, 9500, 14000, 32000, 43000)),
    *((f"matrix-{size}", n) for size, n in (
        (768, 320), (896, 260), (1024, 220), (1152, 430),
        (1280, 460), (1408, 460), (1536, 830), (1664, 940))),
]
TEST = {
    "short": [("wine", 420), ("wine", 1050), ("matrix-832", 275), ("matrix-960", 245)],
    "medium": [("wine", 6800), ("wine", 11200), ("matrix-1216", 450), ("matrix-1344", 445)],
    "long": [("wine", 35500), ("wine", 40000), ("matrix-1536", 945), ("matrix-1600", 900)],
}
CARTPOLE_TRAIN = [("cartpole", n) for n in (3500, 8000, 18000, 32000)]
CARTPOLE_TEST = [("cartpole", 5000), ("cartpole", 25000)]


def workload_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--two-families", action="store_const", const=PREVIOUS,
                        default=WITH_CARTPOLE, dest="output",
                        help="Use the previous Random Forest and NumPy workload")
    return parser


def key(shape):
    environment, steps = shape
    if environment == "cartpole":
        return f"cp{steps}"
    if environment == "wine":
        return f"rf{steps}"
    return f"m{environment.removeprefix('matrix-')}x{steps}"


def spec(shape):
    environment, steps = shape
    if environment == "cartpole":
        algorithm, module = "q-learning-discrete", "rl_workloads.py"
    elif environment == "wine":
        algorithm, module = "random-forest", "classical_ml.py"
    else:
        algorithm, module = "numeric-matmul", "numeric_matmul.py"
    return dict(algorithm=algorithm, environment=environment, maxSteps=steps, seed=42,
                taskAnalysis=collector.analyze(COMMIT, algorithm, environment, steps, module, 42))


def main():
    out = workload_parser().parse_args().output
    groups = {level: list(shapes) for level, shapes in TEST.items()}
    training = list(TRAIN)
    paths = [ROOT / "results-rf-matmul/training.csv"]
    if out == WITH_CARTPOLE:
        groups["short"].extend(CARTPOLE_TEST)
        # The earlier 32 measurements are training data from the same Mac and commit.
        if (PREVIOUS / "training.csv").is_file():
            paths.append(PREVIOUS / "training.csv")
            training = []
        training.extend(CARTPOLE_TRAIN)
    assert set(TRAIN + training).isdisjoint(shape for shapes in groups.values() for shape in shapes)
    out.mkdir(exist_ok=True)
    training_path = out / "training.csv"
    seen = set()
    if training_path.exists():
        with training_path.open() as f:
            seen = {r["experiment_id"] for r in csv.DictReader(f)}
    specs = {s:spec(s) for s in training + [s for group in groups.values() for s in group]}
    for repeat in range(2):
        order = list(training)
        random.Random(18331 + repeat).shuffle(order)
        for shape in order:
            token = f"expanded-{repeat}-{key(shape)}"
            if token in seen:
                continue
            row, _ = measure(specs[shape], token)
            with training_path.open("a", newline="") as f:
                writer = csv.DictWriter(f, row)
                if not seen:
                    writer.writeheader()
                writer.writerow(row)
            seen.add(token)
            print("train", token, round(row["execution_duration_ms"]/1000,2), flush=True)
    rows = predictor.load_observations([*paths, training_path])
    assert len(rows) == (52 if out == WITH_CARTPOLE else 44)
    predictions_path = out / "predictions.json"
    if predictions_path.exists():
        forecasts = json.loads(predictions_path.read_text())["configurations"]
    else:
        model = predictor.RuntimePredictor(rows, neighbors=3)
        host = snapshot()
        forecasts = []
        for level, shapes in groups.items():
            for shape in shapes:
                s = specs[shape]
                estimate = predictor.predict_candidates(model,s["taskAnalysis"],[host])[0]["predictedDurationMs"]
                forecasts.append(dict(config=key(shape), group=level, predicted_ms=estimate,
                                      **{k:v for k,v in s.items() if k != "taskAnalysis"}))
        save(predictions_path, dict(commit=COMMIT, training_rows=len(rows), host=host, configurations=forecasts))
        print("Forecasts frozen.", flush=True)
    random.Random(581).shuffle(forecasts)
    for cfg in forecasts:
        ref_path = out / f"reference-{cfg['config']}.json"
        if ref_path.exists():
            continue
        shape = next(s for s in specs if key(s) == cfg["config"])
        row, metrics = measure(specs[shape], "heldout-" + cfg["config"])
        save(ref_path, dict(config=cfg["config"], duration_ms=row["execution_duration_ms"], metrics=metrics))
        print("heldout", cfg["config"], round(row["execution_duration_ms"]/1000,2), flush=True)


if __name__ == "__main__":
    main()
