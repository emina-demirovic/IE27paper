"""Classical ML workloads invoked by run_experiment.py."""

import json
import sys


def run_random_forest(args):
    if args.simulate_failure:
        print("Intentional experiment failure.", file=sys.stderr)
        return 1

    from sklearn.datasets import (
        fetch_california_housing, load_breast_cancer, load_iris, load_wine,
    )
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.metrics import accuracy_score, mean_squared_error
    from sklearn.model_selection import train_test_split

    loaders = {
        "iris": load_iris,
        "wine": load_wine,
        "breast cancer": load_breast_cancer,
        "california housing": fetch_california_housing,
    }
    dataset = args.environment.strip().casefold()
    if dataset not in loaders:
        print(f"Unknown random-forest dataset: {args.environment}", file=sys.stderr)
        return 1

    try:
        # Keep network time out of measured jobs. Prefetch California once per Worker machine.
        if dataset == "california housing":
            X, y = loaders[dataset](return_X_y=True, download_if_missing=False)
        else:
            X, y = loaders[dataset](return_X_y=True)
    except OSError as error:
        print(f"Could not open {args.environment}: {error}. "
              "Prefetch the dataset using sklearn.datasets.fetch_california_housing().",
              file=sys.stderr)
        return 1

    regression = dataset == "california housing"
    seed = args.seed % (2**32)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed,
        stratify=None if regression else y,
    )
    forest_type = RandomForestRegressor if regression else RandomForestClassifier
    model = forest_type(n_estimators=args.max_steps, random_state=seed, n_jobs=1)
    model.fit(X_train, y_train)
    print("PROGRESS_JSON:" + json.dumps({"currentStep": args.max_steps}), flush=True)
    predictions = model.predict(X_test)
    metrics = {
        "dataset": args.environment,
        "trees": args.max_steps,
        "train_samples": len(y_train),
        "test_samples": len(y_test),
    }
    if regression:
        metrics["rmse"] = float(mean_squared_error(y_test, predictions)) ** 0.5
    else:
        metrics["accuracy"] = float(accuracy_score(y_test, predictions))
    print("RESULT_JSON:" + json.dumps(metrics, allow_nan=False), flush=True)
    return 0
