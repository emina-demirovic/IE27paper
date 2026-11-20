from sklearn.cluster import OPTICS
from sklearn.datasets import make_blobs

def partition(count):
    samples,_=make_blobs(n_samples=count,n_features=14,centers=6,random_state=9)
    clustering=OPTICS(min_samples=12,n_jobs=1)
    labels=clustering.fit_predict(samples)
    return len(set(labels))

print(partition(450))
