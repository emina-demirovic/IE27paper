import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[key] = "1"
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.decomposition import PCA
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
            model = PCA(n_components=min(10, d), svd_solver="full")
            model.fit(x_train)
            result = model.transform(x_test)
    print(result.shape)

experiment(n=10000, d=200, iterations=100, trees=20, depth=8, clusters=8, folds=1, repeats=1)
