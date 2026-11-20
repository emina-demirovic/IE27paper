"""Instrumentacija samo za sopstvene kalibracione eksperimente."""
import json
import math
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'podaci/faze'
THREADS = {k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS')}


def worker(kind, n, d):
    start = perf_counter()
    import numpy as np
    from sklearn.datasets import make_classification
    from sklearn.model_selection import train_test_split
    from sklearn.tree import DecisionTreeClassifier, ExtraTreeClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    imports = perf_counter()-start
    start = perf_counter()
    x, y = make_classification(n_samples=n,n_features=d,n_informative=d//2,random_state=23)
    a,b,c,_ = train_test_split(x,y,test_size=.25,random_state=23)
    prep = perf_counter()-start
    start = perf_counter()
    scaler = StandardScaler().fit(a)
    scaler.transform(a)
    scaler.transform(b)
    scale = perf_counter()-start
    model = {'tree': DecisionTreeClassifier(random_state=23), 'extra': ExtraTreeClassifier(max_features=1,random_state=23),
             'linear': LogisticRegression(max_iter=100)}[kind]
    start = perf_counter()
    model.fit(a,c)
    fit = perf_counter()-start
    start = perf_counter()
    model.predict(b)
    prediction = perf_counter()-start
    print(json.dumps(dict(imports=imports,prep=prep,scale=scale,fit=fit,prediction=prediction,
                          train=len(a),test=len(b),d=d,n=n,kind=kind)))


def calibrate_phases():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in ('tree','extra','linear'):
        for n,d in ((1200,12),(4000,30),(9000,48)):
            for _ in range(3):
                cmd=[sys.executable,str(Path(__file__).resolve()),kind,str(n),str(d)]
                start=perf_counter()
                result=subprocess.run(cmd, capture_output=True,check=True,text=True,env={**os.environ,**THREADS})
                total=perf_counter()-start
                row=json.loads(result.stdout)
                rows.append(dict(row,total=total))
    (OUT/'faze_trening.json').write_text(json.dumps(rows,indent=2))
    return rows


if __name__=='__main__':
    if len(sys.argv)>1:
        worker(sys.argv[1],int(sys.argv[2]),int(sys.argv[3]))
    else:
        calibrate_phases()
