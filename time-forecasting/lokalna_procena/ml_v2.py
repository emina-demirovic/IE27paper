"""Statički profil posla, odvojen overhead, regresija i dijagnostika.

Ulazni izvor se samo parsira. Nema eval/exec/import korisničkog modula.
"""
import ast
import math
import statistics

SPECS = {
    'LogisticRegression': ('logreg', {'max_iter': 100}),
    'DecisionTreeClassifier': ('tree', {'max_depth': 30}),
    'RandomForestClassifier': ('forest', {'n_estimators': 100, 'max_depth': 30}),
    'SGDClassifier': ('sgd', {'max_iter': 1000}),
    'SVC': ('svm', {'C': 1.0}),
    'KMeans': ('kmeans', {'n_clusters': 8, 'max_iter': 300, 'n_init': 1}),
    'MLPClassifier': ('mlp', {'max_iter': 200, 'hidden_layer_sizes': (100,)}),
    'HistGradientBoostingClassifier': ('boost', {'max_iter': 100, 'max_depth': 10}),
    'PCA': ('pca', {}),
}


def literal(node, env):
    """Omeđen evaluator brojeva i tuple/list literala, bez izvršavanja poziva."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [literal(item, env) for item in node.elts]
    if isinstance(node, ast.BinOp):
        a, b = literal(node.left, env), literal(node.right, env)
        if type(a) not in (int, float) or type(b) not in (int, float):
            return None
        operations = {ast.Add: lambda: a+b, ast.Sub: lambda: a-b,
                      ast.Mult: lambda: a*b, ast.Div: lambda: a/b,
                      ast.FloorDiv: lambda: a//b}
        try:
            value = operations[type(node.op)]()
            return value if math.isfinite(value) and abs(value) < 1e18 else None
        except (KeyError, ZeroDivisionError, OverflowError):
            return None
    return None


def profile(source, args=None):
    tree = ast.parse(source)
    env = dict(args or {})
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    def name(call):
        if isinstance(call.func, ast.Name):
            return aliases.get(call.func.id, call.func.id)
        return call.func.attr if isinstance(call.func, ast.Attribute) else ''
    # Jednostavne top-level konstante i završni poziv, uključujući main guard.
    def assignments(body):
        for item in body:
            if isinstance(item, ast.Assign):
                value = literal(item.value, env)
                for target in item.targets:
                    if isinstance(target, ast.Name) and value is not None:
                        env[target.id] = value
    assignments(tree.body)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    tail = tree.body[-1:] if tree.body else []
    for last in tail:
        for call in ast.walk(last):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in functions:
                function = functions[call.func.id]
                params = function.args.posonlyargs + function.args.args
                for parameter, default in zip(params[-len(function.args.defaults):], function.args.defaults):
                    env.setdefault(parameter.arg, literal(default, env))
                for parameter, value in zip(params, call.args):
                    env[parameter.arg] = literal(value, env)
                for kw in call.keywords:
                    if kw.arg:
                        env[kw.arg] = literal(kw.value, env)
                assignments(function.body)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    constructors = [call for call in calls if name(call) in SPECS]
    reasons = []
    if len(constructors) != 1:
        reasons.append('Očekivan je jedan prepoznat ML konstruktor.')
    family, params = 'unknown', {}
    if constructors:
        constructor = constructors[0]
        family, defaults = SPECS[name(constructor)]
        params = dict(defaults)
        for kw in constructor.keywords:
            if kw.arg in defaults:
                value = literal(kw.value, env)
                if value is None:
                    reasons.append(f'Parametar {kw.arg} nije statički poznat.')
                else:
                    params[kw.arg] = value
        if constructor.args:
            reasons.append('Pozicioni parametri konstruktora nisu podržani.')
    n = d = None
    folds, repeats, test_size = 1, 1, .25
    for call in calls:
        keywords = {kw.arg: literal(kw.value, env) for kw in call.keywords if kw.arg}
        if name(call) == 'make_classification':
            n, d = keywords.get('n_samples'), keywords.get('n_features')
        if name(call) in ('StratifiedKFold', 'KFold'):
            folds = keywords.get('n_splits') or (literal(call.args[0], env) if call.args else 5)
        if name(call) == 'train_test_split':
            test_size = keywords.get('test_size', .25)
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call) and name(node.iter) == 'range':
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == 'fit'
                   for c in ast.walk(node)):
                if len(node.iter.args) == 1:
                    value = literal(node.iter.args[0], env)
                    if type(value) in (int, float):
                        repeats *= value
                    else:
                        reasons.append('Broj ponavljanja treninga nije poznat.')
    def number(value, default, label):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            reasons.append(f'Nedostaje validna vrednost: {label}.')
            return default
        return float(value)
    n, d = number(n, 1000, 'n_samples'), number(d, 20, 'n_features')
    folds, repeats = number(folds, 1, 'folds'), number(repeats, 1, 'repeats')
    fraction = 1 - 1/folds if folds > 1 else 1 - (test_size if type(test_size) in (int, float) and 0 < test_size < 1 else .25)
    train_n = n * fraction
    iterations = number(params.get('max_iter', 1), 1, 'max_iter')
    depth = min(number(params.get('max_depth', 30), 30, 'max_depth'), math.log2(max(train_n, 2)))
    work = train_n*d
    if family in ('logreg', 'sgd'):
        work *= iterations
    elif family in ('tree', 'forest'):
        work = train_n * (math.sqrt(d) if family == 'forest' else d) * depth
        work *= number(params.get('n_estimators', 1), 1, 'n_estimators')
    elif family == 'svm':
        work = train_n*train_n*d
    elif family == 'kmeans':
        work *= number(params.get('n_clusters'), 8, 'n_clusters') * iterations
        work *= number(params.get('n_init'), 1, 'n_init')
    elif family == 'mlp':
        hidden = params.get('hidden_layer_sizes', [100])
        if type(hidden) == int:
            hidden = [hidden]
        if not isinstance(hidden, (list, tuple)) or any(type(v) != int or v <= 0 for v in hidden):
            reasons.append('Nepoznata struktura mreže.')
            hidden = [100]
        layers = [d] + list(hidden) + [1]
        work = train_n * iterations * sum(a*b for a, b in zip(layers, layers[1:]))
    elif family == 'boost':
        work *= iterations * depth
    elif family == 'pca':
        work *= d
    jobs = repeats * folds
    scaled = any(name(call) == 'StandardScaler' for call in calls)
    return {'family': family, 'n': n, 'd': d, 'jobs': jobs, 'work': work*jobs,
            'generation': n*d*d, 'scaled': scaled, 'parameters': params,
            'reasons': reasons, 'supported': not reasons}


def vector(p):
    return [math.log1p(p[key]) for key in ('generation', 'work', 'n', 'd', 'jobs')]


def regression(points, overhead):
    import numpy as np
    x = np.array([vector(p['profile']) for p in points])
    # Gornji model je log-linearan; overhead ne sme proizvesti negativan target.
    y = np.log([max(.002, p['seconds']-overhead) for p in points])
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-10] = 1.0
    z = (x-mean)/scale
    weights = np.linalg.solve(z.T@z + 3.0*np.eye(x.shape[1]), z.T@(y-y.mean()))
    return {'mean': mean.tolist(), 'scale': scale.tolist(), 'weights': weights.tolist(),
            'intercept': float(y.mean())}


def compute(reg, p):
    value = reg['intercept'] + sum(w*(x-m)/s for w,x,m,s in
                                  zip(reg['weights'], vector(p), reg['mean'], reg['scale']))
    return math.exp(max(-15, min(20, value)))


def fit(points, overhead):
    families = sorted({p['profile']['family'] for p in points})
    models = {family: regression([p for p in points if p['profile']['family']==family], overhead)
              for family in families}
    global_model = regression(points, overhead)
    # OOF greške samo iz dozvoljenog trening skupa; cela porodica je izostavljena.
    errors = []
    for family in families:
        remaining = [p for p in points if p['profile']['family'] != family]
        if not remaining:
            continue
        reg = regression(remaining, overhead)
        for p in points:
            if p['profile']['family'] == family:
                prediction = overhead + compute(reg, p['profile'])
                errors.append(abs(math.log(p['seconds']/prediction)))
    errors.sort()
    q = errors[min(len(errors)-1, math.ceil(.9*len(errors))-1)] if errors else math.log(10)
    ranges = {key: [min(p['profile'][key] for p in points), max(p['profile'][key] for p in points)]
              for key in ('n', 'd', 'jobs', 'work')}
    return {'type': 'ml_v2', 'overhead': overhead, 'global': global_model,
            'families': models, 'ranges': ranges, 'log_error_q90': q,
            'training_configurations': len(points)}


def predict(model, source, args=None):
    p = profile(source, args)
    known = p['family'] in model['families']
    reg = model['families'].get(p['family'], model['global'])
    seconds = model['overhead'] + compute(reg, p)
    extrapolation = [key for key, (lo, hi) in model['ranges'].items() if not lo <= p[key] <= hi]
    reasons = list(p['reasons'])
    if not known:
        reasons.append('Cela porodica algoritma nedostaje u kalibraciji.')
    if extrapolation:
        reasons.append('Van trening opsega: ' + ', '.join(extrapolation))
    # Empirijski opseg, bez obećanja 90% pokrivenosti budućeg koda.
    factor = math.exp(model['log_error_q90']) * (2 if extrapolation or not p['supported'] else 1)
    return {'seconds': seconds, 'mode': 'model', 'lower_s': max(0, seconds/factor),
            'upper_s': seconds*factor, 'confidence': 'low' if reasons else 'medium',
            'reasons': reasons, 'profile': p, 'overhead_s': model['overhead'],
            'compute_s': seconds-model['overhead'], 'interval_kind': 'empirical_LOFO_not_guaranteed'}
