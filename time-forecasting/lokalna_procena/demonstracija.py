"""Sekvencijalni eksperiment bez mreže i spoljašnjih zavisnosti."""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from runtime_estimator import RuntimeEstimator, extract_args, fingerprint

ROOT = Path(__file__).resolve().parent


def measure(path, repeats):
    durations = []
    for _ in range(repeats):
        start = time.perf_counter()
        subprocess.run([sys.executable, str(path)], cwd=path.parent,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        durations.append(time.perf_counter() - start)
    return durations


def predict(estimator, path, scenario):
    source = path.read_text(encoding='utf-8')
    # Model je već učitan. Meri se jedan ceo poziv estimate(), uključujući AST
    # analizu; čitanje fajla, učitavanje baze i fit nisu deo ovog vremena.
    start = time.perf_counter()
    seconds, mode = estimator.estimate(source)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {'fajl': path.name, 'scenario': scenario, 'rezim': mode,
            'procena_s': seconds, 'vreme_procene_ms': elapsed_ms}


def control(row, path):
    samples = measure(path, 5)
    actual = statistics.median(samples)
    row.update(merenja_s=samples, izmereno_s=actual,
               greska_s=abs(row['procena_s'] - actual))
    return samples


def main():
    data = ROOT / 'podaci'
    data.mkdir(exist_ok=True)
    demo_database = data / 'demo.json'
    demo_database.unlink(missing_ok=True)
    estimator = RuntimeEstimator(demo_database, default=1.0)
    ispis = ROOT / 'primeri/ispis.py'
    source = ispis.read_text(encoding='utf-8')

    a = predict(estimator, ispis, 'A — prazna baza')
    assert a['rezim'] == 'default' and a['procena_s'] == 1.0
    first_samples = control(a, ispis)
    for seconds in first_samples:
        estimator.record(source, seconds, label='A: ispis')
    estimator.save()

    b = predict(estimator, ispis, 'B — poznat kod')
    assert b['procena_s'] == statistics.median(first_samples)
    control(b, ispis)
    # Kontrolna merenja B nisu kalibracija i ne menjaju prethodnu medijanu.
    commented = ROOT / 'primeri/ispis_komentari.py'
    commented.write_text(source + '\n# Prvi komentar\n# Drugi komentar\n'
                         '# Treći komentar\n# Četvrti komentar\n', encoding='utf-8')
    assert fingerprint(source) == fingerprint(commented.read_text(encoding='utf-8'))
    b_comments = predict(estimator, commented, 'B — četiri komentara')
    assert b_comments['rezim'] == 'measured'
    assert b_comments['procena_s'] == b['procena_s']
    control(b_comments, commented)

    training = data / 'trening'
    training.mkdir(exist_ok=True)
    template = (ROOT / 'primeri/zbir.py').read_text(encoding='utf-8')
    for n in (50_000, 200_000, 1_000_000, 3_000_000, 5_000_000):
        text = template.replace('2_000_000', str(n))
        path = training / f'zbir_{n}.py'
        path.write_text(text, encoding='utf-8')
        args = extract_args(text)
        assert args == {'n': n}
        for seconds in measure(path, 3):
            estimator.record(text, seconds, args=args, label=path.name)
    estimator.fit()  # Jedan poziv, van merenja procene.
    estimator.save()
    calibrated = RuntimeEstimator(data / 'kalibracija.json')
    calibrated.records = list(estimator.records)
    calibrated.model = dict(estimator.model)
    calibrated.save()

    zbir = ROOT / 'primeri/zbir.py'
    sortiranje = ROOT / 'primeri/sortiranje.py'
    c1 = predict(estimator, zbir, 'C1 — novi n')
    c2 = predict(estimator, sortiranje, 'C2 — novi algoritam')
    assert [r['rezim'] for r in (a, b, c1, c2)] == ['default', 'measured', 'model', 'model']
    # Obe procene zapisane na disk PRE prvog izvršavanja bilo kog C testa.
    (data / 'procene_pre_C.json').write_text(json.dumps([c1, c2], indent=2,
                                                      ensure_ascii=False) + '\n', encoding='utf-8')
    control(c1, zbir)
    control(c2, sortiranje)
    rows = [a, b, b_comments, c1, c2]
    (data / 'rezultati.json').write_text(json.dumps({
        'python': sys.version, 'executable': sys.executable,
        'greska': 'apsolutna: abs(procena - izmereno)', 'rezultati': rows,
    }, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('fajl | scenario | režim | procena [s] | izmereno [s] | greška [s] | vreme procene [ms]')
    print('--- | --- | --- | ---: | ---: | ---: | ---:')
    for row in rows:
        print(f"{row['fajl']} | {row['scenario']} | {row['rezim']} | "
              f"{row['procena_s']:.6f} | {row['izmereno_s']:.6f} | "
              f"{row['greska_s']:.6f} | {row['vreme_procene_ms']:.4f}")


if __name__ == '__main__':
    main()
