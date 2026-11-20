"""Izbor prediktora po LOFO MAPE, uz odvojenu proveru na novim porodicama."""
import json
import statistics
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, GradientBoostingRegressor

from demonstracija_ml import measure
from ml_v2 import profile, vector, regression, compute

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'podaci/v2'
OUT = ROOT / 'podaci/izbor'
NAMES = ('Medijana', 'V2 ridge', 'Random Forest', 'Extra Trees', 'Gradient boosting')


def load(path):
    return json.loads(path.read_text())


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')


def estimators(points, overhead):
    x = [vector(p['profile']) for p in points]
    y = [p['seconds'] for p in points]
    typical = statistics.median(y)
    ridge = regression(points, overhead)
    models = {'Medijana': lambda p: typical,
              'V2 ridge': lambda p: overhead + compute(ridge, p)}
    candidates = {
        'Random Forest': RandomForestRegressor(n_estimators=128, min_samples_leaf=3, random_state=42, n_jobs=1),
        'Extra Trees': ExtraTreesRegressor(n_estimators=128, min_samples_leaf=3, random_state=42, n_jobs=1),
        'Gradient boosting': GradientBoostingRegressor(loss='huber', n_estimators=80, max_depth=2,
                                                      min_samples_leaf=3, random_state=42),
    }
    for name, model in candidates.items():
        model.fit(x, np.log(y))
        models[name] = lambda p, m=model: float(np.exp(m.predict([vector(p)])[0]))
    return models


def predictions(models, p):
    return {name: fn(p) for name, fn in models.items()}


def metrics(rows):
    result = {}
    for name in NAMES:
        errors = [abs(row['actual'] - row['pred'][name]) for row in rows]
        result[name] = dict(mape=statistics.mean(100*e/r['actual'] for e,r in zip(errors, rows)),
                            mae=statistics.mean(errors))
    return result


def new_scripts():
    # Sve tri porodice su van V2 kalibracije. Različite implementacije
    # predstavljaju i brz vektorizovan fit i skuplje učenje ansambla.
    tasks = [
        ('lda', 'discriminant_analysis', 'LinearDiscriminantAnalysis', ''),
        ('adaboost', 'ensemble', 'AdaBoostClassifier', 'n_estimators=35, random_state=42'),
        ('centroid', 'neighbors', 'NearestCentroid', ''),
    ]
    for family, module, api, params in tasks:
        for n, d in ((2200, 18), (10500, 45)):
            yield f'{family}_{n}', f"""from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
from sklearn.{module} import {api}

def experiment(n, d):
    x, y = make_classification(n_samples=n, n_features=d, n_informative=d//2, random_state=42)
    a, b, c, _ = train_test_split(x, y, test_size=0.25, random_state=42)
    model = {api}({params})
    model.fit(a, c)
    print(model.predict(b).shape)

experiment({n}, {d})
"""


def historical_scores(points, overhead):
    rows = []
    cached = {}
    for test in load(BASE / 'rezultati.json'):
        family = test['config']['algorithm']
        if family not in cached:
            cached[family] = estimators([p for p in points if p['profile']['family'] != family], overhead)
        source = (ROOT / 'primeri_v2' / (test['config']['name'] + '.py')).read_text()
        rows.append(dict(name=test['config']['name'], actual=test['actual'],
                         pred=predictions(cached[family], profile(source))))
    return metrics(rows)


def calibration():
    db = load(BASE / 'kalibracija.json')
    groups = {}
    for record in db['measurements']:
        groups.setdefault(record['fingerprint'], []).append(record)
    return [dict(profile=profile(records[0]['source']), name=records[0]['label'],
                 seconds=statistics.median(r['seconds'] for r in records))
            for records in groups.values()], db['model']['overhead']


def main():
    OUT.mkdir(exist_ok=True, parents=True)
    points, overhead = calibration()
    cv = []
    for family in sorted({p['profile']['family'] for p in points}):
        models = estimators([p for p in points if p['profile']['family'] != family], overhead)
        for p in points:
            if p['profile']['family'] == family:
                cv.append(dict(name=p['name'], actual=p['seconds'], pred=predictions(models, p['profile'])))
    cv_metrics = metrics(cv)
    chosen = min(NAMES, key=lambda name: cv_metrics[name]['mape'])
    final = estimators(points, overhead)
    rows = []
    for name, source in new_scripts():
        (OUT / f'{name}.py').write_text(source)
        start = perf_counter()
        prediction = final[chosen](profile(source))
        elapsed = (perf_counter()-start)*1000
        rows.append(dict(name=name, pred=predictions(final, profile(source)), chosen_s=prediction, latency_ms=elapsed))
    save('pre_izvrsavanja.json', dict(chosen=chosen, cv_metrics=cv_metrics, predictions=rows))
    for row in rows:
        durations, _ = measure(OUT / (row['name'] + '.py'), 5)
        row.update(actual=statistics.median(durations), samples=durations)
    result = dict(chosen=chosen, cv=cv, cv_metrics=cv_metrics, prospective=rows, prospective_metrics=metrics(rows))
    result['historical_metrics'] = historical_scores(points, overhead)
    save('poredjenje.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'cv'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
