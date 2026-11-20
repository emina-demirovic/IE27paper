"""Veći neviđeni poslovi; koristi zamrznut model osnovnog ML eksperimenta."""
import json
import statistics
import time

from demonstracija_ml import DATA, ROOT, SCRIPTS, config, source_for, measure, save
from runtime_estimator import RuntimeEstimator, fingerprint


def main():
    estimator = RuntimeEstimator(DATA / 'kalibracija.json')
    if estimator.model is None:
        raise SystemExit('Prvo pokrenite python3 demonstracija_ml.py')
    baseline = statistics.median(r['seconds'] for r in estimator.records)
    old = RuntimeEstimator(ROOT / 'podaci/kalibracija.json')
    tests = [
        config('svm_30000', 'svm', 30000, 80, 'neviđen algoritam — veliki'),
        config('mlp_20000', 'mlp', 20000, 100, 'neviđen algoritam — veliki', iterations=200),
    ]
    predictions = []
    for c in tests:
        source = source_for(c)
        (SCRIPTS / (c['name'] + '.py')).write_text(source, encoding='utf-8')
        assert fingerprint(source) not in {r['fingerprint'] for r in estimator.records}
        start = time.perf_counter()
        seconds, mode = estimator.estimate(source)
        elapsed = (time.perf_counter() - start) * 1000
        assert mode == 'model'
        old_seconds, old_mode = old.estimate(source)
        predictions.append(dict(config=c, procena_s=seconds, rezim=mode,
                                vreme_procene_ms=elapsed, stara_procena_s=old_seconds,
                                stari_rezim=old_mode))
    save('teski_procene_pre_testova.json', predictions)
    for row in predictions:
        print('Merim: ' + row['config']['name'], flush=True)
        durations, warnings = measure(SCRIPTS / (row['config']['name'] + '.py'), 5)
        actual = statistics.median(durations)
        error = abs(actual - row['procena_s'])
        row.update(merenja_s=durations, upozorenja=warnings, izmereno_s=actual,
                   greska_s=error, greska_pct=error / actual * 100,
                   stara_greska_s=abs(actual - row['stara_procena_s']))
    save('teski_rezultati.json', predictions)
    rows = json.loads((DATA / 'rezultati.json').read_text()) + predictions
    groups = {}
    for title, selected in (
        ('svi', rows),
        ('poznate porodice', [r for r in rows if not r['config']['scenario'].startswith('neviđen')]),
        ('neviđene porodice', [r for r in rows if r['config']['scenario'].startswith('neviđen')]),
        ('veliki neviđeni', predictions),
    ):
        groups[title] = dict(count=len(selected),
                            model_mape=statistics.mean(r['greska_pct'] for r in selected),
                            constant_mape=statistics.mean(abs(baseline-r['izmereno_s']) / r['izmereno_s'] * 100 for r in selected))
    save('poredjenje.json', dict(konstantna_procena_s=baseline, grupe=groups))
    lines = ['# Svi rezultati ML eksperimenata', '',
             'Stvarno vreme: medijana pet procesa. Greška: apsolutna. Model je zamrznut pre testova.', '',
             '| Fajl | Scenario | Režim | n × d | Procena [s] | Stara [s] | Izmereno [s] | Greška [s] | Greška [%] | Procena [ms] |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        c = r['config']
        lines.append(f'| {c["name"]}.py | {c["scenario"]} | {r["rezim"]} | {c["n"]} × {c["d"]} | '
                     f'{r["procena_s"]:.4f} | {r["stara_procena_s"]:.4f} | {r["izmereno_s"]:.4f} | '
                     f'{r["greska_s"]:.4f} | {r["greska_pct"]:.1f} | {r["vreme_procene_ms"]:.3f} |')
    lines += ['', f'Konstantna procena (medijana trening merenja): {baseline:.4f} s.', '',
              '| Grupa | Broj | Model MAPE [%] | Konstantna procena MAPE [%] |',
              '|---|---:|---:|---:|']
    for name, group in groups.items():
        lines.append(f'| {name} | {group["count"]} | {group["model_mape"]:.1f} | {group["constant_mape"]:.1f} |')
    lines += ['', 'MAPE je srednja apsolutna procentualna greška, nije garancija za budući kod.',
              'Veliki testovi nisu korišćeni za promenu modela. Njihove procene su zamrznute zajedno pre oba izvršavanja.', '']
    (ROOT / 'REZULTATI_ML.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
