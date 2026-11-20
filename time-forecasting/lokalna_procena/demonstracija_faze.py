"""Svež test celih ML klasa i Python implementacija na istom računaru."""
import argparse
import csv
import json
import math
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from textwrap import indent

from demonstracija_ml import measure
from faze_kalibracija import OUT, ROOT, calibrate_phases
from faze_model import Analysis, OPS, predict
from runtime_estimator import fingerprint
import nepoznat
import ml_v2

median=statistics.median
SCRIPTS=OUT/'testovi'


def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))


def calibrate_ops():
    import numpy as np
    from scipy.optimize import nnls
    kernels=['pass','s += i','s += i%61','s += seq[i%32]','counts[i%32]=i',
             's += counts.get(i%32,0)','a = [0]*32','s += abs(i)',
             'a = sorted(seq)','s += (i*3+1)%97','s += (i%7)*(i%17)',
             'a = [0]*256','a = sorted(long_seq)', 's += (i*3+7)*(i+9)',
             'counts[0]=counts.get(0,0)+counts.get(1,1)+counts.get(2,2)', 's += i%5+i%7+i%11']
    rows=[]
    for body in kernels:
        for n in (3500,15000):
            code=('def bench(n,seq,long_seq):\n    s=0\n    counts={}\n    for i in range(n):\n'
                  +indent(body,'        ')+'\n    return s\n')
            env={}
            # Isključivo gornje naše mikromere, nikada izvor prosleđen CLI-ju.
            exec(code,env)
            seq=list(range(32))
            long_seq=list(range(256))
            random.Random(18).shuffle(seq)
            random.Random(19).shuffle(long_seq)
            samples=[]
            for _ in range(7):
                start=time.perf_counter()
                env['bench'](n,seq,long_seq)
                samples.append(time.perf_counter()-start)
            ast_code=code+f'bench({n},list(range(32)),list(range(256)))'
            analysis=Analysis({})
            analysis.parse(ast_code,None)
            rows.append(dict(body=body,n=n,ops=dict(analysis.ops),samples=samples))
    x=np.array([[r['ops'].get(k,0) for k in OPS] for r in rows])
    times=np.array([median(r['samples']) for r in rows])
    x=x/times[:,None]
    norms=np.maximum(np.linalg.norm(x,axis=0),1)
    weights=nnls(x/norms,np.ones_like(times))[0]/norms
    write('mikromere.json',rows)
    return dict(zip(OPS,weights.tolist()))


def make_csv():
    path=SCRIPTS/'observations.csv'
    rng=random.Random(1234)
    with path.open('w') as out:
        writer=csv.writer(out)
        for i in range(14000):
            x=[rng.randrange(-200,201) for _ in range(28)]
            writer.writerow(x+[int(sum(x[:8])>0)])
    return path


def model_from(rows):
    rates={}
    for kind in ('tree','extra','linear'):
        subset=[r for r in rows if r['kind']==kind]
        def units(r):
            n,d=r['train'],r['d']
            if kind=='linear': return n*d
            return n*math.log2(n)*(d if kind=='tree' else 1)
        rates[kind]=median(r['fit']/units(r) for r in subset)
    rates.update(data=median(r['prep']/(r['n']*r['d']) for r in rows),
                 scale=median(r['scale']/(r['n']*r['d']) for r in rows),
                 predict_row=median(r['prediction']/r['test'] for r in rows),
                 imports=median(r['imports'] for r in rows))
    blank=ROOT/'primeri_v2/overhead_python.py'
    rates['startup']=median(measure(blank,5)[0])
    numpy_times=[]
    for _ in range(3):
        start=time.perf_counter()
        subprocess.run([sys.executable,'-c','import numpy'],check=True)
        numpy_times.append(time.perf_counter()-start)
    rates['numpy_import']=max(0,median(numpy_times)-rates['startup'])
    import numpy as np
    path=OUT/'kalibracija_io.csv'
    np.savetxt(path,np.arange(9000*13).reshape(9000,13),fmt='%d',delimiter=',')
    costs=[]
    for _ in range(5):
        start=time.perf_counter()
        np.loadtxt(path,delimiter=',')
        costs.append((time.perf_counter()-start)/path.stat().st_size)
    rates['csv_byte']=median(costs)
    rates.update(type='phase_static',ops=calibrate_ops())
    # Greške V3 na ranijem skupu za nierazrešene pozive, pre svežih testova.
    history={}
    directory=ROOT/'podaci/nepoznat'
    for r in json.loads((directory/'merenja.json').read_text()):
        p=directory/'skripte'/r['name']
        detail=predict(rates,p.read_text(),p)
        if detail['unresolved']:
            history.setdefault(r['group'], []).append(abs(detail['seconds']/r['actual']-1)*100)
    rates['unknown_history']={group:dict(count=len(errors),median_ape_pct=median(errors),
                                  p90_ape_pct=sorted(errors)[math.ceil(.9*len(errors))-1])
                              for group,errors in history.items()}
    return rates


def cases():
    helper='''def accumulate(length, width):
    total=0
    for row in range(length):
        for col in range(width):
            total += ((row*11+col)%113)*((row+col*5)%29)
    return total
'''
    (SCRIPTS/'numeric_helper.py').write_text(helper)
    python={
        'cross_moment': 'from numeric_helper import accumulate as moment\n\ndef run(n,d):\n    return moment(n,d)\n',
        'transition_counts': 'def run(n,d):\n    counts={}\n    for i in range(n):\n        key=(i*13)%d\n        counts[key]=counts.get(key,0)+1\n    return len(counts)\n',
        'spectral_bins': 'def run(n,d):\n    buf=[0]*d\n    for i in range(n):\n        idx=(i*17)%d\n        buf[idx]+=i%19\n    return sum(buf)\n',
        'block_order': 'def run(n,d):\n    scores=[(idx*9973)%50021 for idx in range(n)]\n    scores.sort()\n    return scores[n//2]\n',
        'class_distance': 'class Metric:\n    def evaluate(self,n,d):\n        s=0\n        for i in range(n):\n            for j in range(d):\n                s+=(i%11-j%7)*(i%11-j%7)\n        return s\n\ndef run(n,d):\n    metric=Metric()\n    return metric.evaluate(n,d)\n',
        'scratch_space': 'def run(n,d):\n    total=0\n    for i in range(n):\n        cell=[0]*d\n        cell[i%d]=1\n        total+=cell[i%d]\n    return total\n',
    }
    for family,body in python.items():
        for n,d in ((19000,18),(155000,36),(450000,62)):
            yield family,'Python',f'{family}_{n}',body+f'\nprint(run({n},{d}))\n'
    # Finalne klase nisu korišćene u kalibraciji faza.
    ml=[
      ('bag_reg','ensemble','BaggingRegressor','n_estimators=k, max_samples=fraction, max_features=0.75, random_state=4','make_regression'),
      ('extra_reg','ensemble','ExtraTreesRegressor','n_estimators=k, max_depth=10, random_state=4','make_regression'),
      ('isolation','ensemble','IsolationForest','n_estimators=k, random_state=4','make_blobs'),
      ('scaled_ridge','linear_model','Ridge','alpha=3','make_regression'),
      ('latent_pls','cross_decomposition','PLSRegression','n_components=4','make_regression'),
      ('mixture_diag','mixture','GaussianMixture',"n_components=6,covariance_type='diag',random_state=13",'make_blobs'),
      ('opaque_svr','svm','LinearSVR','random_state=4, max_iter=150','make_regression'),
    ]
    for family,module,api,params,data in ml:
        for n,d,k,fraction in ((2100,16,10,.35),(7200,28,18,.65),(14500,44,30,.95)):
            setup=f'from sklearn.datasets import {data}\nfrom sklearn.{module} import {api} as Algorithm\nfrom sklearn.model_selection import train_test_split\n'
            expr=f'Algorithm({params})'
            if family=='scaled_ridge':
                setup+='from sklearn.preprocessing import StandardScaler\nfrom sklearn.pipeline import make_pipeline\n'
                expr='make_pipeline(StandardScaler(), '+expr+')'
            body=f'\ndef train(n,d,k,fraction):\n    points,target={data}(n_samples=n,n_features=d,random_state=4)\n    x,hold,y,_=train_test_split(points,target,test_size=.2,random_state=4)\n    learner={expr}\n    learner.fit(x,y)\n    return learner.predict(hold)\n'
            yield family,'sklearn',f'{family}_{n}',setup+body+f'\nprint(train({n},{d},{k},{fraction}).shape)\n'
    for frac in (.35, .85):
        body='''from pathlib import Path
import numpy as np
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import BaggingClassifier
from sklearn.model_selection import train_test_split

def read_table():
    dataset=np.loadtxt(Path(__file__).with_name("observations.csv"),delimiter=",")
    return dataset[:,:-1],dataset[:,-1]

def run(fraction):
    x,y=read_table()
    train,hold,labels,_=train_test_split(x,y,test_size=.3,random_state=5)
    forest=BaggingClassifier(estimator=DecisionTreeClassifier(max_depth=7),n_estimators=23,max_samples=fraction,random_state=5)
    forest.fit(train,labels)
    return forest.predict(hold)
'''
        yield 'csv_bag','sklearn',f'csv_bag_{int(frac*100)}',body+f'\nprint(run({frac}).shape)\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--use-phase-samples',action='store_true',help='Ponovo koristi sačuvana instrumentirana merenja.')
    opt=parser.parse_args()
    SCRIPTS.mkdir(parents=True,exist_ok=True)
    raw=json.loads((OUT/'faze_trening.json').read_text()) if opt.use_phase_samples else calibrate_phases()
    model=model_from(raw)
    write('model.json',dict(model=model,measurements=[]))
    old=json.loads((ROOT/'podaci/nepoznat/model.json').read_text())['model']
    v2=json.loads((ROOT/'podaci/v2/kalibracija.json').read_text())['model']
    make_csv()
    prior={fingerprint(p.read_text()) for folder in ('primeri','primeri_v2','primeri_ml','podaci/nepoznat/skripte','podaci/izbor') for p in (ROOT/folder).glob('*.py')}
    rows=[]
    for family,group,name,src in cases():
        assert fingerprint(src) not in prior
        prior.add(fingerprint(src))
        path=SCRIPTS/(name+'.py')
        path.write_text(src)
        start=time.perf_counter()
        detail=predict(model,src,path)
        elapsed=(time.perf_counter()-start)*1000
        static=nepoznat.predict(old,src)
        ridge=ml_v2.predict(v2,src)['seconds']
        rows.append(dict(family=family,group=group,name=name,detail=detail,ms=elapsed,
                         v3=detail['seconds'],static=static,ridge=ridge,route=static if group=='Python' else ridge))
    random.Random(453).shuffle(rows)
    write('procene.json',rows)
    for i,row in enumerate(rows,1):
        path=SCRIPTS/(row['name']+'.py')
        times,warnings=measure(path,5)
        row.update(actual=median(times),samples=times,warnings=warnings)
        write('rezultati.json',rows)
        print(i,len(rows),row['name'],round(row['actual'],3),flush=True)
    report(rows)


def metrics(rows,key):
    errors=[abs(r[key]-r['actual']) for r in rows]
    return (statistics.mean(errors),statistics.mean(100*e/r['actual'] for e,r in zip(errors,rows)),
            sum(r['actual']>2*r[key] for r in rows))


def report(rows):
    lines=['# Procena po fazama na novim implementacijama','',
           '41 fajl iz 14 obrazaca, pet procesa po fajlu. Stvarno vreme je medijana od pokretanja do izlaza. '
           'Route koristi statičku metodu za Python i V2 Ridge za sklearn. Izbor iz prethodnog testa zamrznut je pre ovih merenja.','',
           '| Grupa | Metoda | MAE [s] | MAPE [%] | Stvarno > 2 × procena |','|---|---|---:|---:|---:|']
    for group in ('Python','sklearn','svi'):
        subset=[r for r in rows if group=='svi' or r['group']==group]
        for key in ('static','ridge','route','v3'):
            a,b,c=metrics(subset,key)
            lines.append(f'| {group} ({len(subset)}) | {key} | {a:.4f} | {b:.1f} | {c} |')
    lines+=['','| Skripta | V3 [s] | Route [s] | Stvarno [s] | Greška V3 [s] | Procena [ms] |','|---|---:|---:|---:|---:|---:|']
    for r in sorted(rows,key=lambda item:item['name']):
        lines.append(f"| {r['name']} | {r['v3']:.4f} | {r['route']:.4f} | {r['actual']:.4f} | {abs(r['actual']-r['v3']):.4f} | {r['ms']:.3f} |")
    (ROOT/'REZULTATI_FAZE.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    main()
