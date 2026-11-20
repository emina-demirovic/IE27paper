"""Drugi odvojeni skup: šest novih tela, bez menjanja ili treniranja V3."""
import json
import sys
import time
from statistics import median
from demonstracija_faze import ROOT, OUT, measure, fingerprint, metrics
from faze_model import predict
import nepoznat
import ml_v2

DIR=OUT/'nezavisni'

PROGRAMS={
    'prefix_queries':'''def prefix(values):
    out=[0]*(len(values)+1)
    for i in range(len(values)):
        out[i+1]=out[i]+values[i]
    return out

def evaluate(n):
    data=[(i*137)%997 for i in range(n)]
    acc=prefix(data)
    return sum(acc[i]-acc[i//2] for i in range(n))

print(evaluate(NUM))
''',
    'levenshtein':'''def distance(n):
    left=[(i*7)%17 for i in range(n)]
    right=[(i*3)%13 for i in range(n)]
    previous=list(range(n+1))
    for i in range(n):
        current=[i+1]*(n+1)
        for j in range(n):
            current[j+1]=min(current[j]+1,previous[j+1]+1,previous[j]+(left[i]!=right[j]))
        previous=current
    return previous[-1]

print(distance(NUM))
''',
    'binary_lookup':'''def bisect_index(seq, target):
    low=0
    high=len(seq)
    while low<high:
        middle=(low+high)//2
        if seq[middle]<target:
            low=middle+1
        else:
            high=middle
    return low

def run(n):
    seq=list(range(n))
    total=0
    for i in range(n):
        total+=bisect_index(seq,(i*997)%n)
    return total

print(run(NUM))
''',
    'random_projection':'''from sklearn.datasets import make_blobs
from sklearn.random_projection import GaussianRandomProjection as Project

def embed(n):
    points,_=make_blobs(n_samples=n,n_features=64,random_state=10)
    reducer=Project(n_components=12,random_state=12)
    embedded=reducer.fit_transform(points)
    return embedded.shape

print(embed(NUM))
''',
    'covariance':'''from sklearn.covariance import LedoitWolf
from sklearn.datasets import make_regression

class CovarianceJob:
    def score(self, records):
        data,_=make_regression(n_samples=records,n_features=50,random_state=7)
        fitted=LedoitWolf().fit(data)
        return fitted.score(data)

def main(records):
    job=CovarianceJob()
    return job.score(records)

print(main(NUM))
''',
    'optics':'''from sklearn.cluster import OPTICS
from sklearn.datasets import make_blobs

def partition(count):
    samples,_=make_blobs(n_samples=count,n_features=14,centers=6,random_state=9)
    clustering=OPTICS(min_samples=12,n_jobs=1)
    labels=clustering.fit_predict(samples)
    return len(set(labels))

print(partition(NUM))
'''}
SIZES={'prefix_queries':(20000,350000),'levenshtein':(140,700),'binary_lookup':(12000,210000),
       'random_projection':(3500,28000),'covariance':(4000,24000),'optics':(450,3200)}


def read(path):
    return json.loads(path.read_text())


def freeze():
    DIR.mkdir(exist_ok=True)
    model=read(OUT/'model.json')['model']
    old=read(ROOT/'podaci/nepoznat/model.json')['model']
    v2=read(ROOT/'podaci/v2/kalibracija.json')['model']
    previous={fingerprint(p.read_text()) for p in ROOT.rglob('*.py') if DIR not in p.parents}
    rows=[]
    for family,body in PROGRAMS.items():
        group='sklearn' if 'from sklearn.' in body else 'Python'
        for n in SIZES[family]:
            source=body.replace('NUM',str(n))
            assert fingerprint(source) not in previous
            name=f'{family}_{n}'
            path=DIR/(name+'.py')
            path.write_text(source)
            start=time.perf_counter()
            detail=predict(model,source,path)
            ms=(time.perf_counter()-start)*1000
            static=nepoznat.predict(old,source)
            ridge=ml_v2.predict(v2,source)['seconds']
            rows.append(dict(name=name,group=group,family=family,v3=detail['seconds'],detail=detail,ms=ms,
                             static=static,ridge=ridge,route=static if group=='Python' else ridge))
    (DIR/'procene.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))


def controls():
    rows=read(DIR/'procene.json')
    model=read(OUT/'model.json')['model']
    for row in rows:
        path=DIR/(row['name']+'.py')
        if predict(model,path.read_text(),path)!=row['detail']:
            raise ValueError('Model ili izvor se promenio nakon čuvanja procena.')
    for row in rows:
        samples,warnings=measure(DIR/(row['name']+'.py'),5)
        row.update(samples=samples,warnings=warnings,actual=median(samples))
        (DIR/'rezultati.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        print(row['name'],flush=True)


def report_all():
    base=read(OUT/'rezultati.json')
    independent=read(DIR/'rezultati.json')
    all_rows=base+independent
    dev=[]
    model=read(OUT/'model.json')['model']
    for row in read(ROOT/'podaci/nepoznat/merenja.json'):
        path=ROOT/'podaci/nepoznat/skripte'/row['name']
        detail=predict(model,path.read_text(),path)
        dev.append(dict(actual=row['actual'],group=row['group'],v3=detail['seconds'],
                        route=row['static'] if row['group']=='Python' else row['ridge'],name=row['name']))
    (OUT/'razvojni_128.json').write_text(json.dumps(dev,indent=2))
    lines=['# Procena po fazama', '',
           'Razvojni skup ima 128 starih merenja. Zasebni završni skupovi imaju 41 i 12 fajlova. '
           'Svaka tačka je medijana pet procesa. Oba skupa imaju procene sačuvane pre svojih kontrola. '
           'Model koristi iste koeficijente u oba skupa. Trošak procene uključuje statičku analizu i, gde je primenljivo, pregled dimenzija lokalnog CSV-a.', '',
           'Skup od 41 fajla obuhvata nove konfiguracije, uključujući obrasce pregledane u probnoj seriji. '
           'Poslednjih 12 fajlova iz šest novih tela koristi zaseban izvor i nove porodice računanja. '
           'Kalibracione ML klase su DecisionTreeClassifier, ExtraTreeClassifier i LogisticRegression. '
           'Procena ansambala koristi kalibraciju osnovnih stabala. Skup je sintetički, sa fiksnim seed-om i jednom numeričkom niti.', '',
           '| Skup | Grupa | Broj | Metoda | MAE [s] | MAPE [%] | Stvarno > 2 × procena |',
           '|---|---|---:|---|---:|---:|---:|']
    for title,rows in [('Razvojni',dev),('Nove konfiguracije',base),('Nezavisna tela',independent),('Svi završni',all_rows)]:
        for group in ('Python','sklearn','svi'):
            selected=[r for r in rows if group=='svi' or r['group']==group]
            for key in ('route','v3'):
                a,b,c=metrics(selected,key)
                lines.append(f'| {title} | {group} | {len(selected)} | {key} | {a:.4f} | {b:.1f} | {c} |')
    lines+=['', 'Route bira raniju statičku procenu za Python i V2 Ridge za sklearn. V3 procenjuje svaku fazu i sabira trajanja.', '',
            '| Skripta | Grupa | V3 [s] | Route [s] | Statički [s] | Ridge [s] | Izmereno [s] | Aps. greška V3 [s] | Procena [ms] |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in all_rows:
        lines.append(f"| {r['name']} | {r['group']} | {r['v3']:.4f} | {r['route']:.4f} | {r['static']:.4f} | {r['ridge']:.4f} | {r['actual']:.4f} | {abs(r['v3']-r['actual']):.4f} | {r['ms']:.3f} |")
    (ROOT/'REZULTATI_FAZE.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    if '--controls' not in sys.argv: freeze()
    if '--freeze' not in sys.argv:
        controls()
        report_all()
