"""Lokalni estimator: AST memorija i linearni model vremena prema n.

Analiza koristi samo ast; korisnički kod se nikada ne uvozi niti izvršava.
"""
import ast
import hashlib
import json
import math
import statistics
from pathlib import Path


def fingerprint(source):
    tree = ast.parse(source)
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def extract_args(source):
    """Čita numeričke literale završnog poziva, uključujući print(f(n)).

    Podržava pozicione/imenovane literalne argumente lokalno definisane
    funkcije. Izrazi, promenljive i dinamički ulazi se ne evaluiraju.
    """
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not tree.body or not isinstance(tree.body[-1], ast.Expr):
        return {}
    for call in ast.walk(tree.body[-1]):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        function = functions.get(call.func.id)
        if function is None:
            continue
        names = [arg.arg for arg in function.args.posonlyargs + function.args.args]
        pairs = list(zip(names, call.args)) + [(kw.arg, kw.value) for kw in call.keywords]
        result = {}
        for name, value in pairs:
            if name is not None:
                try:
                    n = ast.literal_eval(value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if type(n) in (int, float) and math.isfinite(n) and n >= 0:
                    result[name] = n
        return result
    return {}


class RuntimeEstimator:
    def __init__(self, database, default=1.0):
        self.database = Path(database)
        self.default = default
        self.records = []
        self.model = None
        if self.database.exists():
            state = json.loads(self.database.read_text(encoding='utf-8'))
            self.records = state['measurements']
            self.model = state['model']

    def estimate(self, source, args=None, *, path=None):
        key = fingerprint(source)
        args = extract_args(source) if args is None else args
        measured = [r['seconds'] for r in self.records
                    if r['fingerprint'] == key and r['args'] == args]
        if measured:
            return statistics.median(measured), 'measured'
        if self.model is not None:
            if self.model['type'] == 'phase_static':
                from faze_model import predict
                return predict(self.model, source, path)['seconds'], 'model'
            if self.model['type'] == 'unknown_static':
                from nepoznat import predict
                return predict(self.model, source), 'model'
            if self.model['type'] == 'ml_v2':
                from ml_v2 import predict
                return predict(self.model, source, args)['seconds'], 'model'
            if self.model['type'] == 'static_ml':
                from ml_features import predict_model
                return predict_model(self.model, source, args), 'model'
            n = args.get('n', 0)
            prediction = self.model['intercept'] + self.model['seconds_per_n'] * n
            return max(0.0, prediction), 'model'
        return self.default, 'default'

    def record(self, source, seconds, args=None, label=''):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Trajanje mora biti konačno i nenegativno.')
        self.records.append({'fingerprint': fingerprint(source),
                             'source': source,
                             'args': extract_args(source) if args is None else args,
                             'seconds': seconds, 'label': label})

    def fit(self):
        # Samo primeri sa poznatim n učestvuju u regresiji; po jedna
        # medijana po konfiguraciji sprečava različite težine ponavljanja.
        groups = {}
        for record in self.records:
            if 'n' in record['args']:
                key = (record['fingerprint'], record['args']['n'])
                groups.setdefault(key, []).append(record['seconds'])
        points = [(key[1], statistics.median(values)) for key, values in groups.items()]
        if len({x for x, _ in points}) < 2:
            raise ValueError('Potrebne su bar dve različite vrednosti n.')
        mean_x = statistics.mean(x for x, _ in points)
        mean_y = statistics.mean(y for _, y in points)
        slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum(
            (x - mean_x) ** 2 for x, _ in points)
        self.model = {'type': 'linear_n', 'seconds_per_n': slope,
                      'intercept': mean_y - slope * mean_x,
                      'training_configurations': len(points)}

    def save(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.database.write_text(json.dumps({'version': 1, 'model': self.model,
                                            'measurements': self.records}, indent=2) + '\n',
                                 encoding='utf-8')
