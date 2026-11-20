from sklearn.ensemble import ExtraTreesClassifier as Learner
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split

def run(n, d, k):
    x, y = make_classification(n_samples=n, n_features=d, n_informative=d//2, random_state=13)
    a, b, labels, _ = train_test_split(x,y,test_size=0.2,random_state=13)
    model = Learner(n_estimators=k, random_state=42, n_jobs=1)
    model.fit(a, labels)
    print(model.predict(b).shape)

run(12000, 50, 40)
