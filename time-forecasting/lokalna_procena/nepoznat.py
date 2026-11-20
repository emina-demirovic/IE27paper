"""Procena nepoznatog koda pomoću vidljivih petlji i parametara rada."""
import ast
import math
from ml_v2 import literal
from runtime_estimator import extract_args


def span(iterator, env):
    if isinstance(iterator, ast.Call) and isinstance(iterator.func, ast.Name) and iterator.func.id == 'range':
        values = [literal(arg, env) for arg in iterator.args]
        if 1 <= len(values) <= 3 and all(type(v) is int for v in values):
            try:
                return len(range(*values))
            except (ValueError, OverflowError):
                pass
    return 1


def iterations(node, env):
    if isinstance(node, ast.For):
        count = span(node.iter, env)
        return count * (1 + sum(iterations(item, env) for item in node.body))
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return math.prod(span(g.iter, env) for g in node.generators)
    return sum(iterations(child, env) for child in ast.iter_child_nodes(node))


def predict(model, source):
    tree = ast.parse(source)
    env = extract_args(source)
    imports = set()
    ensemble = 1
    size = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.add((node.module or '').split('.')[0])
        elif isinstance(node, ast.Import):
            imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                value = literal(kw.value, env)
                if type(value) is int and value > 0:
                    if kw.arg == 'n_estimators':
                        ensemble = max(ensemble, value)
                    if kw.arg in ('n_samples', 'n_features'):
                        size[kw.arg] = value
    # Broji samo telo direktno pozvane završne funkcije i top-level rad.
    funcs = {item.name: item for item in tree.body if isinstance(item, ast.FunctionDef)}
    loops = sum(iterations(item, env) for item in tree.body if not isinstance(item, (ast.FunctionDef, ast.ClassDef)))
    if tree.body:
        for node in ast.walk(tree.body[-1]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
                loops += iterations(funcs[node.func.id], env)
    if 'sklearn' in imports:
        cells = size.get('n_samples', env.get('n', 1000)) * size.get('n_features', env.get('d', 20))
        base = model['sklearn_s'] + cells * model['cell_s']
        # Prenos iz šume: rad po članu ansambla može znatno varirati.
        base += (ensemble-1) * cells * model['ensemble_cell_s']
    else:
        base = model['python_s']
    return base + loops * model['iteration_s']
