"""Lokalna prospektivna provera. Pet novih procesa za svaki od 128 fajlova."""
import json
import random
import statistics
import time
from pathlib import Path
from textwrap import dedent, indent

from demonstracija_ml import measure
from ml_v2 import predict as ridge
from nepoznat import predict
from runtime_estimator import fingerprint

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'podaci/nepoznat'
SCRIPTS = OUT/'skripte'
median = statistics.median

# Različita tela algoritama. Svako telo generiše po šest testova.
KERNELS = {
    'hinge_loss': 'bad = 0.0\nfor i in range(n):\n    margin = ((i * 37) % 257 - 128) / 64\n    bad += max(0, 1 - margin)\nreturn bad / n',
    'brier_score': 'error = 0.0\nfor i in range(n):\n    error += ((i % 101) / 100 - (i % 2)) ** 2\nreturn error / n',
    'confusion_matrix': 'counts = [[0]*d for _ in range(d)]\nfor i in range(n):\n    counts[i % d][(i * 7 // 3) % d] += 1\nreturn counts[0][0]',
    'online_variance': 'mean = total = 0.0\nfor i in range(n):\n    val = (i*13) % 503\n    delta = val - mean\n    mean += delta / (i+1)\n    total += delta * (val-mean)\nreturn total / n',
    'reservoir_sampling': 'rng = Random(13)\nsample = list(range(d))\nfor i in range(d,n):\n    j = rng.randrange(i+1)\n    if j < d: sample[j] = i\nreturn sample[0]',
    'one_hot': 's = 0\nfor i in range(n):\n    v = [0]*d\n    v[i%d] = 1\n    s += sum(v)\nreturn s',
    'histogram': 'bins = [0]*d\nfor i in range(n):\n    bins[((i*479) % 1021)*d//1021] += 1\nreturn max(bins)',
    'feature_hashing': 'counts = [0]*d\nfor i in range(n):\n    counts[(i*2654435761) % d] += 1 if i % 3 else -1\nreturn max(counts)',
    'ema_filter': 'acc = 0.0\nfor i in range(n):\n    acc = 0.97*acc + 0.03*((i*19)%101)\nreturn acc',
    'log_loss': 'acc = 0.0\nfor i in range(n):\n    prob = ((i%99)+1)/101\n    acc -= log(prob if i%2 else 1-prob)\nreturn acc/n',
    'l1_distance': 'out = 0\nfor i in range(n):\n    for j in range(d):\n        out += abs((i+j)%17 - (j*5)%11)\nreturn out',
    'dot_product': 'weights = [j/11 for j in range(d)]\ns = 0.0\nfor i in range(n):\n    for j in range(d):\n        s += weights[j]*((i+j)%13)\nreturn s',
    'hamming_distance': 'acc = 0\nfor i in range(n):\n    for j in range(d):\n        acc += ((i >> j) & 1) != ((i >> (j+1)) & 1)\nreturn acc',
    'moving_average': 'window = [0]*d\ns = 0\nfor i in range(n):\n    k = i%d\n    s -= window[k]\n    window[k] = (i*29)%127\n    s += window[k]\nreturn s/d',
    'rank_percentile': 'values = [(i*997)%7919 for i in range(n)]\nvalues.sort()\nreturn values[9*n//10]',
    'run_length_encoding': 'tokens = []\nlast = None\nfor i in range(n):\n    v = (i//7)%d\n    if v != last: tokens.append([v,1])\n    else: tokens[-1][1] += 1\n    last = v\nreturn len(tokens)',
}
LIBRARIES = [
    ('linear_model','RidgeClassifier',''), ('linear_model','Perceptron','random_state=42'),
    ('naive_bayes','BernoulliNB',''), ('discriminant_analysis','QuadraticDiscriminantAnalysis',''),
    ('ensemble','BaggingClassifier','n_estimators=k, random_state=42, n_jobs=1'),
    ('ensemble','IsolationForest','n_estimators=k, random_state=42, n_jobs=1'),
    ('ensemble','ExtraTreesClassifier','n_estimators=k, random_state=42, n_jobs=1'),
    ('neural_network','BernoulliRBM','n_components=16, n_iter=5, random_state=42'),
]


def scripts():
    for family, body in KERNELS.items():
        for n, d in [(3000,8),(12000,16),(30000,12),(70000,24),(120000,32),(250000,48)]:
            imports = 'from random import Random\n' if family=='reservoir_sampling' else 'from math import log\n' if family=='log_loss' else ''
            yield family, 'Python', n, d, imports+f'def {family}(n, d):\n'+indent(body,'    ')+f'\n\nprint({family}({n}, {d}))\n'
    for module, family, params in LIBRARIES:
        for n,d,k in [(750,12,8),(2200,24,16),(6500,36,25),(12000,50,40)]:
            call = 'transform' if family=='BernoulliRBM' else 'predict'
            yield family,'sklearn',n,d,dedent(f'''\
                from sklearn.{module} import {family} as Learner
                from sklearn.datasets import make_classification
                from sklearn.model_selection import train_test_split

                def run(n, d, k):
                    x, y = make_classification(n_samples=n, n_features=d, n_informative=d//2, random_state=13)
                    a, b, labels, _ = train_test_split(x,y,test_size=0.2,random_state=13)
                    model = Learner({params})
                    model.fit(a, labels)
                    print(model.{call}(b).shape)

                run({n}, {d}, {k})
            ''')


def save(name, value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def median_points(records):
    groups = {}
    for r in records:
        groups.setdefault(r['label'], []).append(r)
    return [(g[0]['args'], median(r['seconds'] for r in g), label) for label,g in groups.items()]


def calibrate(db, base):
    overhead = db['model']['overhead']
    train = median_points(db['measurements'])
    ordinary = [(s-overhead)/(a['n']*a['d']) for a,s,label in train if
                a['repeats']==1 and a['folds']==1 and label.startswith(('train_sgd_', 'train_logreg_'))]
    forests = [(s-overhead)/(a['n']*a['d']*a['trees']) for a,s,label in train if
               label.startswith('train_forest_') and a['repeats']==1]
    origin = median(r['seconds'] for r in base['measurements'] if not r['args'])
    return dict(type='unknown_static',python_s=origin,sklearn_s=overhead,
                iteration_s=base['model']['seconds_per_n'],cell_s=max(0,median(ordinary)),
                ensemble_cell_s=max(0,median(forests)))


def metrics(rows, method):
    errors = [abs(r[method]-r['actual']) for r in rows]
    percents = [100*e/r['actual'] for e,r in zip(errors,rows)]
    return statistics.mean(percents),statistics.mean(errors),max(percents)


def report(rows):
    lines=['# Potpuno novi zadaci','', '128 skripti, 24 različita tela/ML klase, 5 procesa po skripti. '
           'Skup ima 96 Python i 32 sklearn testa. V2 i konstanta su kalibrisani za sklearn. '
           'Nova metoda prenosi i odvojenu Python kalibraciju. Sva vremena uključuju pokretanje procesa.', '',
           '| Grupa | Broj | Metoda | MAPE [%] | MAE [s] | Najveća greška [%] |',
           '|---|---:|---|---:|---:|---:|']
    for group in ['svi','Python','sklearn']:
        selected=[r for r in rows if group=='svi' or r['group']==group]
        for method in ('static','startup','ridge','constant'):
            m,a,w=metrics(selected,method)
            lines.append(f'| {group} | {len(selected)} | {method} | {m:.1f} | {a:.4f} | {w:.1f} |')
    lines += ['', '| Telo algoritma ili ML klasa | Broj skripti | MAPE static [%] | MAPE startup [%] | MAPE Ridge [%] |',
              '|---|---:|---:|---:|---:|']
    for family in sorted({row['family'] for row in rows}):
        selected = [r for r in rows if r['family'] == family]
        values = [metrics(selected, method)[0] for method in ('static', 'startup', 'ridge')]
        lines.append(f'| {family} | {len(selected)} | {values[0]:.1f} | {values[1]:.1f} | {values[2]:.1f} |')
    lines += ['', 'static koristi import, procenu iteracija i generički trošak po članu ansambla. '
              'startup koristi samo Python ili sklearn start sa importima. ridge je prethodni V2, constant medijana ML kalibracije.', '',
              '| Fajl | n | d | static [s] | startup [s] | Ridge [s] | konstanta [s] | stvarno [s] | aps. greška static [s] | greška [%] | procena [ms] |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in sorted(rows,key=lambda v:(v['family'],v['n'])):
        error=abs(r['static']-r['actual'])
        lines.append(f"| {r['name']} | {r['n']} | {r['d']} | {r['static']:.4f} | {r['startup']:.4f} | {r['ridge']:.4f} | {r['constant']:.4f} | {r['actual']:.4f} | {error:.4f} | {100*error/r['actual']:.1f} | {r['ms']:.3f} |")
    model = json.loads((OUT/'model.json').read_text())['model']
    lines += ['', '## Kako se računaju procene', '',
              'Sve veličine vremena su u sekundama. Svaka od četiri metode dobija isti test fajl.',
              '', '1. **Konstanta** vraća medijanu 46 medijana V2 kalibracionih konfiguracija.',
              '2. **Startup** za ove grupe vraća izmereno trajanje ranije minimalne Python skripte ili procesa sa zajedničkim sklearn importima.',
              '3. **V2 Ridge** koristi opšti model jer svih 24 tipa izostaje iz njegovog spiska prepoznatih konstruktora. '
              'Za pet pokazatelja (priprema podataka, obim rada, n, d i broj treninga) računa log(1+x), pa standardizuje po trening skupu. '
              'Regresija minimizuje zbir kvadrata odstupanja od log(max(0.002, stvarno − startup)) uz penal 3 puta zbir kvadrata težina. '
              'Procena je startup + exp(slobodni član + skalarni proizvod težina i standardizovanih pokazatelja). '
              'Gde V2 ne prepozna dimenzije koristi n=1000 i d=20. Za ove ručne Python funkcije dodaje i sklearn startup.',
              '4. **Static** koristi prenesene troškove sa istog računara. Za Python računa P + aI. Za sklearn računa S + aI + bnd + c(k−1)nd. '
              'I je procenjeni broj izvršavanja tela vidljivih petlji, n broj redova, d broj karakteristika, k literalno razrešiv n_estimators (inače 1).',
              '', f'P={model["python_s"]:.8f} i S={model["sklearn_s"]:.8f} dolaze iz zasebnih kalibracija pokretanja. '
              f'a={model["iteration_s"]:.6g} s/iteraciji je nagib ranije regresije za zbir kvadrata. '
              f'b={model["cell_s"]:.6g} s/elementu je medijana (trajanje−S)/(nd) iz kalibracije SGD-a i logističke regresije sa jednim treningom. '
              f'c={model["ensemble_cell_s"]:.6g} s/elementu po članu je medijana (trajanje−S)/(ndk) iz kalibracije šume sa jednim ponavljanjem.',
              '', 'Stvarno vreme je medijana pet procesa. MAE je prosek |procena−stvarno| u sekundama. '
              'MAPE je 100 puta prosek |procena−stvarno|/stvarno, sa jednakom težinom svake skripte.', '']
    (ROOT/'REZULTATI_NEPOZNAT.md').write_text('\n'.join(lines)+'\n')


def main():
    SCRIPTS.mkdir(parents=True,exist_ok=True)
    db=json.loads((ROOT/'podaci/v2/kalibracija.json').read_text())
    base=json.loads((ROOT/'podaci/kalibracija.json').read_text())
    model=calibrate(db,base)
    save('model.json',dict(model=model,measurements=[]))
    constant=median(s for _,s,_ in median_points(db['measurements']))
    past={fingerprint(p.read_text()) for folder in ['primeri','primeri_ml','primeri_v2','podaci/trening','podaci/izbor'] for p in (ROOT/folder).glob('*.py')}
    rows=[]
    for family,group,n,d,src in scripts():
        name=f'{family}_{n}.py'
        key=fingerprint(src)
        assert key not in past
        past.add(key)
        (SCRIPTS/name).write_text(src)
        start=time.perf_counter()
        estimate=predict(model,src)
        ms=(time.perf_counter()-start)*1000
        rows.append(dict(name=name,family=family,group=group,n=n,d=d,fingerprint=key,static=estimate,ms=ms,
                         ridge=ridge(db['model'],src)['seconds'],constant=constant,
                         startup=model['sklearn_s' if group=='sklearn' else 'python_s']))
    random.Random(42).shuffle(rows)
    save('pre_izvrsavanja.json',rows)
    results=[]
    for i,row in enumerate(rows,1):
        times,warnings=measure(SCRIPTS/row['name'],5)
        results.append(dict(row,actual=median(times),samples=times,warnings=warnings))
        save('merenja.json',results)
        if i%8==0: print(i,'/',len(rows),flush=True)
    report(results)


if __name__=='__main__':
    main()
