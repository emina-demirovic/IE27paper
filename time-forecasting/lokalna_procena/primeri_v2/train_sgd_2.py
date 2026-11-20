import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[key] = "1"
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.linear_model import SGDClassifier
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
            model = SGDClassifier(max_iter=iterations, tol=None, random_state=42)
            model.fit(x_train, y_train)
            result = model.predict(x_test)
    print(result.shape)

experiment(n=2000, d=80, iterations=30, trees=20, depth=4, clusters=4, folds=1, repeats=1)
