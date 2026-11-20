from sklearn.linear_model import RidgeClassifier as Learner
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split

def run(n, d, k):
    x, y = make_classification(n_samples=n, n_features=d, n_informative=d//2, random_state=13)
    a, b, labels, _ = train_test_split(x,y,test_size=0.2,random_state=13)
    model = Learner()
    model.fit(a, labels)
    print(model.predict(b).shape)

run(750, 12, 8)
