"""V2: nezavisni finalni fajlovi, LOFO i uporedivi baseline modeli.

Ponovno pokretanje pravi nova merenja. --resume nastavlja isti sačuvani plan.
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

from demonstracija_ml import config, source_for, measure, THREAD_ENV
from ml_features import fit_model, predict_model
from ml_v2 import fit, predict, profile
from runtime_estimator import RuntimeEstimator, extract_args, fingerprint

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'podaci/v2'
SCRIPTS = ROOT / 'primeri_v2'
FAMILIES = ('logreg', 'tree', 'forest', 'sgd', 'svm', 'kmeans', 'mlp')


def save(name, value):
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def source(c):
    text = source_for(c)
    # Fiksiran broj MLP epoha; rani prekid više ne prikriva opterećenje.
    if c['algorithm'] == 'mlp':
        text = text.replace('early_stopping=False,', 'early_stopping=False, tol=0.0, n_iter_no_change=10000,')
    return text


def plan():
    training, tests = [], []
    for algorithm in FAMILIES:
        base = dict(iterations=30, trees=20, depth=4, clusters=4)
        configurations = [dict(n=2000, d=20), dict(n=8000, d=20), dict(n=2000, d=80),
                          dict(n=12000 if algorithm=='svm' else 2000, d=20),
                          dict(n=2000, d=20, repeats=3), dict(n=12000, d=60)]
        # Svaki od prvih pet parova menja jedan efektivni faktor.
        if algorithm != 'svm':
            effective = {'logreg': 'iterations', 'tree': 'depth', 'forest': 'trees',
                         'sgd': 'iterations', 'kmeans': 'clusters', 'mlp': 'iterations'}[algorithm]
            configurations[3][effective] = base[effective]*4
        for i, options in enumerate(configurations):
            settings = {**base, **options}
            training.append(config(f'train_{algorithm}_{i}', algorithm, settings.pop('n'), settings.pop('d'),
                                   'kalibracija', **settings))
        tests.append(config(f'test_{algorithm}_novi', algorithm, 5000, 40, 'novi parametri',
                            iterations=60, trees=50, depth=10, clusters=12))
        tests.append(config(f'test_{algorithm}_veci', algorithm, 22000, 80, 'ekstrapolacija',
                            iterations=120, trees=100, depth=12, clusters=16))
    training.extend([
        config('train_forest_dugi', 'forest', 20000, 80, 'dugi', trees=300, depth=16, repeats=2),
        config('train_mlp_dugi', 'mlp', 18000, 80, 'dugi', iterations=150),
        config('train_logreg_cv', 'logreg', 6000, 30, 'CV', folds=3, scaled=True),
        config('train_logreg_scaler', 'logreg', 2000, 20, 'skaliranje', iterations=30, scaled=True),
    ])
    tests.extend([
        config('test_logreg_cv5', 'logreg', 9000, 40, 'novi tok', folds=5, scaled=True),
        config('test_boost_nikad', 'boost', 15000, 60, 'potpuno izostavljena porodica', iterations=180),
        config('test_pca_nikad', 'pca', 10000, 200, 'potpuno izostavljena porodica'),
    ])
    return training, tests


def write_report(rows):
    lines = ['# V2: procena novih ML zadataka', '',
             'Svi redovi su model procene za prethodno neizvršene finalne fajlove. '
             'LOFO model nikada ne dobija merenja porodice iz svog reda. '
             'Medijana pet novih procesa uključuje pokretanje, import, podatke, fit i predikciju.', '',
             '| Fajl | Scenario | V2 LOFO [s] | V1 isti trening [s] | Konstanta [s] | V2 poznata porodica [s] | Stvarno [s] | LOFO greška [s] | LOFO greška [%] | Empirijski opseg [s] | Procena [ms] |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|']
    for row in rows:
        if 'actual' not in row:
            continue
        detail = row['lofo']
        lines.append(f'| {row["config"]["name"]}.py | {row["config"]["scenario"]} | '
                     f'{detail["seconds"]:.3f} | {row["v1"]:.3f} | {row["constant"]:.3f} | '
                     f'{row["known"]["seconds"]:.3f} | {row["actual"]:.3f} | '
                     f'{row["error_s"]:.3f} | {row["error_pct"]:.1f} | '
                     f'{detail["lower_s"]:.3f}–{detail["upper_s"]:.3f} | {row["estimate_ms"]:.3f} |')
    summary = {}
    for title, selected in [('svi', rows),
                            ('izostavljene porodice sa kalibracionim parom', [r for r in rows if r['config']['algorithm'] in FAMILIES]),
                            ('potpuno izostavljene porodice', [r for r in rows if r['config']['algorithm'] not in FAMILIES])]:
        selected = [r for r in selected if 'actual' in r]
        if not selected:
            continue
        values = {}
        for model in ('lofo', 'known', 'v1', 'constant', 'old_frozen'):
            predictions = [r[model]['seconds'] if isinstance(r[model], dict) else r[model] for r in selected]
            percentages = [abs(p-r['actual'])/r['actual']*100 for p,r in zip(predictions, selected)]
            values[model] = {'mape': statistics.mean(percentages),
                             'mae': statistics.mean(abs(p-r['actual']) for p,r in zip(predictions, selected)),
                             'worst_pct': max(percentages)}
        values['interval_coverage'] = sum(r['lofo']['lower_s'] <= r['actual'] <= r['lofo']['upper_s'] for r in selected)/len(selected)
        summary[title] = values
    lines += ['', '| Grupa | V2 LOFO MAPE [%] | V1 isti trening [%] | Konstanta [%] | V2 poznata porodica [%] |',
              '|---|---:|---:|---:|---:|']
    for title, values in summary.items():
        lines.append(f'| {title} | {values["lofo"]["mape"]:.1f} | {values["v1"]["mape"]:.1f} | '
                     f'{values["constant"]["mape"]:.1f} | {values["known"]["mape"]:.1f} |')
    lines += ['', 'V1 je ista prethodna metoda ponovo obučena na potpuno istom dozvoljenom trening skupu kao LOFO V2. '
              'Konstanta je medijana trajanja tog trening skupa. V2 poznata porodica koristi i kalibraciju te porodice, '
              'ali nikada finalne testove. Njena kolona nije rezultat za neviđenu porodicu.', '',
              'Opsezi su empirijski, izvedeni iz unutrašnjeg izostavljanja porodica. Nisu garantovani intervali od 90%. '
              'Sve LOFO procene imaju nisku pouzdanost. Stara zamrznuta V1 procena, upozorenja i sva pojedinačna '
              'merenja nalaze se u podaci/v2/rezultati.json.', '']
    (ROOT / 'REZULTATI_V2.md').write_text('\n'.join(lines), encoding='utf-8')
    save('poredjenje.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true')
    options = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    SCRIPTS.mkdir(exist_ok=True)
    training, tests = plan()
    manifest = {'training': training, 'tests': tests, 'sources': {c['name']: fingerprint(source(c)) for c in training+tests}}
    # Promena implementacije/protokola ne sme tiho koristiti stari cache.
    manifest['implementation'] = hashlib.sha256((Path(__file__).read_bytes() + (ROOT/'ml_v2.py').read_bytes())).hexdigest()
    if options.resume and (DATA/'plan.json').exists():
        if json.loads((DATA/'plan.json').read_text()) != manifest:
            raise SystemExit('Plan ili implementacija promenjeni; pokrenite bez --resume.')
    save('plan.json', manifest)
    for c in training+tests:
        (SCRIPTS/(c['name']+'.py')).write_text(source(c), encoding='utf-8')
    cache = json.loads((DATA/'trening.json').read_text()) if options.resume and (DATA/'trening.json').exists() else {}
    if 'overhead' not in cache:
        overhead = {}
        for name, text in [('python', 'pass\n'), ('imports', source(training[0]).rsplit('\nexperiment(', 1)[0]+'\n')]:
            path = SCRIPTS/f'overhead_{name}.py'
            path.write_text(text, encoding='utf-8')
            durations, warnings = measure(path, 5)
            overhead[name] = {'durations': durations, 'median': statistics.median(durations), 'warnings': warnings}
        cache['overhead'] = overhead
        save('trening.json', cache)
    for i,c in enumerate(training, 1):
        if c['name'] not in cache:
            durations, warnings = measure(SCRIPTS/(c['name']+'.py'), 3)
            cache[c['name']] = {'durations': durations, 'warnings': warnings}
            save('trening.json', cache)
        print(f'Trening {i}/{len(training)} {c["name"]}: {statistics.median(cache[c["name"]]["durations"]):.3f} s', flush=True)
    overhead = cache['overhead']['imports']['median']
    points, records = [], []
    for c in training:
        text = source(c)
        p = profile(text)
        assert p['family'] == c['algorithm'] and p['supported'], p
        points.append({'name': c['name'], 'profile': p, 'seconds': statistics.median(cache[c['name']]['durations'])})
        for seconds in cache[c['name']]['durations']:
            records.append({'source': text, 'args': extract_args(text), 'fingerprint': fingerprint(text), 'seconds': seconds, 'label': c['name']})
    full = fit(points, overhead)
    save('kalibracija.json', {'version': 2, 'model': full, 'measurements': records})
    models, v1_models, constants, audit = {}, {}, {}, {}
    for family in FAMILIES + ('boost', 'pca'):
        allowed = [p for p in points if p['profile']['family'] != family]
        allowed_names = {p['name'] for p in allowed}
        permitted_records = [r for r in records if r['label'] in allowed_names]
        models[family] = fit(allowed, overhead)
        v1_models[family] = fit_model(permitted_records)
        constants[family] = statistics.median(p['seconds'] for p in allowed)
        audit[family] = {'training_names': sorted(allowed_names), 'model': models[family],
                         'v1_model': v1_models[family], 'constant': constants[family]}
    save('fold_models.json', audit)
    old = RuntimeEstimator(ROOT/'podaci/ml/kalibracija.json')
    rows = []
    # Kod i modeli su zamrznuti pre svih finalnih kontrolnih izvršavanja.
    for c in tests:
        text = source(c)
        assert fingerprint(text) not in {r['fingerprint'] for r in records}
        family = c['algorithm']
        start = time.perf_counter()
        detail = predict(models[family], text)
        elapsed = (time.perf_counter()-start)*1000
        rows.append({'config': c, 'lofo': detail, 'known': predict(full, text),
                     'v1': predict_model(v1_models[family], text, extract_args(text)),
                     'constant': constants[family], 'old_frozen': old.estimate(text)[0],
                     'estimate_ms': elapsed})
    if options.resume and (DATA/'procene_pre_testova.json').exists():
        previous = json.loads((DATA/'procene_pre_testova.json').read_text())
        assert [r['lofo']['seconds'] for r in rows] == [r['lofo']['seconds'] for r in previous]
        rows = previous
    else:
        save('procene_pre_testova.json', rows)
    print('Svih 17 finalnih procena sačuvano; kontrola počinje.', flush=True)
    completed = json.loads((DATA/'rezultati.json').read_text()) if options.resume and (DATA/'rezultati.json').exists() else []
    completed = {r['config']['name']: r for r in completed if 'actual' in r}
    for i,row in enumerate(rows, 1):
        c = row['config']
        if c['name'] in completed:
            row.update(completed[c['name']])
        else:
            durations, warnings = measure(SCRIPTS/(c['name']+'.py'), 5)
            actual = statistics.median(durations)
            error = abs(actual-row['lofo']['seconds'])
            row.update(durations=durations, warnings=warnings, actual=actual, error_s=error, error_pct=100*error/actual)
            save('rezultati.json', rows)
        print(f'Test {i}/{len(rows)} {c["name"]}: {row["actual"]:.3f} s, LOFO greška {row["error_pct"]:.1f}%', flush=True)
    import sklearn
    import numpy
    save('okruzenje.json', {'python': sys.version, 'platform': platform.platform(),
                           'sklearn': sklearn.__version__, 'numpy': numpy.__version__, 'threads': THREAD_ENV})
    write_report(rows)


if __name__ == '__main__':
    main()
