"""Statičke karakteristike i regresija; ulazni kod se ne izvršava.

Svi koeficijenti/normalizacije uče se isključivo iz trening skupa.
"""
import ast
import math
import statistics

PARAMETERS = ('n', 'd', 'iterations', 'trees', 'depth', 'clusters', 'folds', 'repeats')
APIS = ('LogisticRegression', 'DecisionTreeClassifier', 'RandomForestClassifier',
        'SGDClassifier', 'SVC', 'KNeighborsClassifier', 'KMeans', 'PCA',
        'MLPClassifier', 'HistGradientBoostingClassifier', 'GaussianNB')


def features(source, args):
    tree = ast.parse(source)
    calls = [node.func.id if isinstance(node.func, ast.Name) else node.func.attr
             for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, (ast.Name, ast.Attribute))]
    values = [math.log1p(args.get(name, 1)) for name in PARAMETERS]
    values += [float(api in calls) for api in APIS]
    values += [math.log1p(sum(isinstance(node, kind) for node in ast.walk(tree)))
               for kind in (ast.For, ast.Call, ast.ImportFrom, ast.ListComp)]
    return values


def fit_model(records):
    # numpy je potreban samo za fit; predikcija je čisti Python.
    import numpy as np
    groups = {}
    for record in records:
        groups.setdefault(record['fingerprint'], []).append(record)
    examples = list(groups.values())
    x = np.array([features(g[0]['source'], g[0]['args']) for g in examples])
    y = np.log([statistics.median(r['seconds'] for r in g) for g in examples])
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x - mean) / scale
    # Fiksna regularizacija; ne podešava se prema test rezultatima.
    coefficients = np.linalg.solve(z.T @ z + 10.0 * np.eye(z.shape[1]), z.T @ (y - y.mean()))
    return {'type': 'static_ml', 'mean': mean.tolist(), 'scale': scale.tolist(),
            'coefficients': coefficients.tolist(), 'intercept': float(y.mean()),
            'training_configurations': len(examples), 'ridge_alpha': 10.0}


def predict_model(model, source, args):
    x = features(source, args)
    log_seconds = model['intercept'] + sum(
        weight * (value - mean) / scale for value, mean, scale, weight in
        zip(x, model['mean'], model['scale'], model['coefficients']))
    return math.exp(max(-20.0, min(20.0, log_seconds)))
