"""Lokalni ML benchmark: trening 3x, kontrola 5x, novi proces za svaki uzorak."""
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from ml_features import fit_model
from runtime_estimator import RuntimeEstimator, extract_args, fingerprint

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'podaci/ml'
SCRIPTS = ROOT / 'primeri_ml'
THREAD_ENV = {key: '1' for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                                 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
                                 'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS')}

MODELS = {
    'logreg': ('LogisticRegression', 'LogisticRegression(max_iter=iterations, solver="lbfgs")'),
    'tree': ('DecisionTreeClassifier', 'DecisionTreeClassifier(max_depth=depth, random_state=42)'),
    'forest': ('RandomForestClassifier', 'RandomForestClassifier(n_estimators=trees, max_depth=depth, n_jobs=1, random_state=42)'),
    'sgd': ('SGDClassifier', 'SGDClassifier(max_iter=iterations, tol=None, random_state=42)'),
    'svm': ('SVC', 'SVC(C=1.0, kernel="rbf")'),
    'knn': ('KNeighborsClassifier', 'KNeighborsClassifier(n_neighbors=5, n_jobs=1)'),
    'kmeans': ('KMeans', 'KMeans(n_clusters=clusters, n_init=3, max_iter=iterations, random_state=42)'),
    'pca': ('PCA', 'PCA(n_components=min(10, d), svd_solver="full")'),
    'mlp': ('MLPClassifier', 'MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=iterations, early_stopping=False, random_state=42)'),
    'boost': ('HistGradientBoostingClassifier', 'HistGradientBoostingClassifier(max_iter=iterations, max_depth=depth, random_state=42)'),
    'nb': ('GaussianNB', 'GaussianNB()'),
}
MODULES = dict(logreg='linear_model', tree='tree', forest='ensemble', sgd='linear_model',
               svm='svm', knn='neighbors', kmeans='cluster', pca='decomposition',
               mlp='neural_network', boost='ensemble', nb='naive_bayes')


def config(name, algorithm, n, d, scenario, **kwargs):
    return dict(name=name, algorithm=algorithm, n=n, d=d, scenario=scenario,
                iterations=kwargs.get('iterations', 100), trees=kwargs.get('trees', 20),
                depth=kwargs.get('depth', 8), clusters=kwargs.get('clusters', 8),
                folds=kwargs.get('folds', 1), repeats=kwargs.get('repeats', 1),
                scaled=kwargs.get('scaled', False))


def source_for(c):
    api, expression = MODELS[c['algorithm']]
    if c['scaled']:
        expression = f'make_pipeline(StandardScaler(), {expression})'
    fit = 'model.fit(x_train, y_train)'
    predict = 'model.predict(x_test)'
    if c['algorithm'] == 'pca':
        fit, predict = 'model.fit(x_train)', 'model.transform(x_test)'
    elif c['algorithm'] == 'kmeans':
        fit = 'model.fit(x_train)'
    arguments = ', '.join(f'{name}={c[name]}' for name in
                          ('n', 'd', 'iterations', 'trees', 'depth', 'clusters', 'folds', 'repeats'))
    return f'''import os
for key in {tuple(THREAD_ENV)!r}:
    os.environ[key] = "1"
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.{MODULES[c['algorithm']]} import {api}
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

def experiment(n, d, iterations, trees, depth, clusters, folds, repeats):
    x, y = make_classification(n_samples=n, n_features=d,
                               n_informative=max(2, d // 2), n_redundant=0,
                               random_state=42)
    for _ in range(repeats):
        if folds > 1:
            splits = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42).split(x, y)
        else:
            splits = [train_test_split(range(n), test_size=0.25, random_state=42)]
        for train, test in splits:
            x_train, x_test, y_train = x[train], x[test], y[train]
            model = {expression}
            {fit}
            result = {predict}
    print(result.shape)

experiment({arguments})
'''


def measure(path, count):
    times, warnings = [], []
    for _ in range(count):
        start = time.perf_counter()
        process = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                                 env={**os.environ, **THREAD_ENV}, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, text=True, timeout=120, check=True)
        times.append(time.perf_counter() - start)
        warnings.append(process.stderr)
    return times, warnings


def save(name, value):
    (DATA / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    SCRIPTS.mkdir(exist_ok=True)
    training = []
    for algorithm in ('logreg', 'tree', 'forest', 'sgd'):
        for i, (n, d) in enumerate(((800, 10), (2500, 30), (6000, 20), (8000, 60))):
            training.append(config(f'train_{algorithm}_{i}', algorithm, n, d, 'trening',
                                   iterations=(30, 60, 100, 150)[i], trees=(10, 20, 40, 60)[i],
                                   depth=(4, 8, 12, 16)[i], scaled=i % 2 == 1,
                                   repeats=2 if i == 2 else 1, folds=3 if i == 3 else 1))
    tests = [
        config('logreg_novi_ulaz', 'logreg', 4000, 40, 'novi parametri', scaled=True),
        config('logreg_ekstrapolacija', 'logreg', 16000, 100, 'van trening opsega', scaled=True, iterations=200),
        config('tree_dubina_3', 'tree', 5000, 40, 'novi parametri', depth=3),
        config('tree_dubina_25', 'tree', 5000, 40, 'novi parametri', depth=25),
        config('forest_15', 'forest', 4000, 30, 'novi parametri', trees=15),
        config('forest_100', 'forest', 4000, 30, 'novi parametri', trees=100),
        config('sgd_iter_20', 'sgd', 5000, 40, 'novi parametri', iterations=20),
        config('sgd_iter_300', 'sgd', 5000, 40, 'novi parametri', iterations=300),
        config('logreg_cv5', 'logreg', 4000, 30, 'novi tok: CV=5', folds=5, scaled=True),
        config('logreg_ponovi5', 'logreg', 4000, 30, 'novi tok: ponovi=5', repeats=5, scaled=True),
        config('svm_mali', 'svm', 1500, 20, 'neviđen algoritam'),
        config('svm_veliki', 'svm', 8000, 60, 'neviđen algoritam'),
        config('knn_mali', 'knn', 2000, 10, 'neviđen algoritam'),
        config('knn_veliki', 'knn', 12000, 80, 'neviđen algoritam'),
        config('kmeans_4', 'kmeans', 5000, 30, 'neviđen algoritam', clusters=4),
        config('kmeans_32', 'kmeans', 5000, 30, 'neviđen algoritam', clusters=32),
        config('pca', 'pca', 8000, 120, 'neviđen algoritam'),
        config('mlp_20', 'mlp', 3000, 30, 'neviđen algoritam', iterations=20),
        config('mlp_100', 'mlp', 3000, 30, 'neviđen algoritam', iterations=100),
        config('boost', 'boost', 6000, 40, 'neviđen algoritam', iterations=150),
        config('naive_bayes', 'nb', 8000, 60, 'neviđen algoritam'),
    ]
    for c in training + tests:
        (SCRIPTS / (c['name'] + '.py')).write_text(source_for(c), encoding='utf-8')
    save('plan.json', {'training': training, 'tests': tests})
    # Generisanje i AST analiza testova ne izvršavaju njihov kod.
    database = DATA / 'kalibracija.json'
    database.unlink(missing_ok=True)
    estimator = RuntimeEstimator(database)
    calibration = []
    for index, c in enumerate(training, 1):
        path = SCRIPTS / (c['name'] + '.py')
        source = path.read_text()
        durations, warnings = measure(path, 3)
        for duration in durations:
            estimator.record(source, duration, args=extract_args(source), label=c['name'])
        calibration.append(dict(config=c, durations=durations, warnings=warnings))
        print(f'Trening {index}/{len(training)}: {c["name"]}', flush=True)
    estimator.model = fit_model(estimator.records)
    estimator.save()
    save('trening_merenja.json', calibration)
    old = RuntimeEstimator(ROOT / 'podaci/kalibracija.json')
    rows = []
    trained_keys = {r['fingerprint'] for r in estimator.records}
    for c in tests:
        source = (SCRIPTS / (c['name'] + '.py')).read_text()
        assert fingerprint(source) not in trained_keys
        start = time.perf_counter()
        prediction, mode = estimator.estimate(source)
        latency = (time.perf_counter() - start) * 1000
        baseline, baseline_mode = old.estimate(source)
        assert mode == 'model'
        rows.append(dict(config=c, procena_s=prediction, rezim=mode,
                         vreme_procene_ms=latency, stara_procena_s=baseline,
                         stari_rezim=baseline_mode))
    save('procene_pre_testova.json', rows)  # SVE procene pre SVIH test izvršavanja.
    print('Sve test procene sačuvane; počinju kontrolna izvršavanja.', flush=True)
    for index, row in enumerate(rows, 1):
        times, warnings = measure(SCRIPTS / (row['config']['name'] + '.py'), 5)
        actual = statistics.median(times)
        error = abs(row['procena_s'] - actual)
        row.update(merenja_s=times, upozorenja=warnings, izmereno_s=actual,
                   greska_s=error, greska_pct=100 * error / actual,
                   stara_greska_s=abs(row['stara_procena_s'] - actual))
        save('rezultati.json', rows)
        print(f'Test {index}/{len(rows)}: {row["config"]["name"]}', flush=True)
    import numpy
    import sklearn
    save('okruzenje.json', dict(python=sys.version, executable=sys.executable,
                               platform=platform.platform(), machine=platform.machine(),
                               numpy=numpy.__version__, sklearn=sklearn.__version__,
                               threads=THREAD_ENV))
    lines = ['# Rezultati lokalnih ML eksperimenata', '',
             'Svi testovi: režim `model`; medijana 5 novih procesa. Greška je apsolutna.', '',
             '| Fajl | Scenario | n | d | Procena [s] | Stara procena [s] | Izmereno [s] | Greška [s] | Greška [%] | Procena [ms] |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        c = r['config']
        lines.append(f'| {c["name"]}.py | {c["scenario"]} | {c["n"]} | {c["d"]} | '
                     f'{r["procena_s"]:.4f} | {r["stara_procena_s"]:.4f} | {r["izmereno_s"]:.4f} | '
                     f'{r["greska_s"]:.4f} | {r["greska_pct"]:.1f} | {r["vreme_procene_ms"]:.3f} |')
    lines += ['', 'Parametri svih konfiguracija: `podaci/ml/plan.json`. Sva pojedinačna merenja i upozorenja: `podaci/ml/rezultati.json`.', '']
    (ROOT / 'REZULTATI_ML.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
