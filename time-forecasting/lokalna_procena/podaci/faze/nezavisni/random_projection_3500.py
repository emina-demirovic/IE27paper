from sklearn.datasets import make_blobs
from sklearn.random_projection import GaussianRandomProjection as Project

def embed(n):
    points,_=make_blobs(n_samples=n,n_features=64,random_state=10)
    reducer=Project(n_components=12,random_state=12)
    embedded=reducer.fit_transform(points)
    return embedded.shape

print(embed(3500))
