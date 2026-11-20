from sklearn.covariance import LedoitWolf
from sklearn.datasets import make_regression

class CovarianceJob:
    def score(self, records):
        data,_=make_regression(n_samples=records,n_features=50,random_state=7)
        fitted=LedoitWolf().fit(data)
        return fitted.score(data)

def main(records):
    job=CovarianceJob()
    return job.score(records)

print(main(24000))
