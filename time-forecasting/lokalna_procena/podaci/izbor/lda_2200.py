from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

def experiment(n, d):
    x, y = make_classification(n_samples=n, n_features=d, n_informative=d//2, random_state=42)
    a, b, c, _ = train_test_split(x, y, test_size=0.25, random_state=42)
    model = LinearDiscriminantAnalysis()
    model.fit(a, c)
    print(model.predict(b).shape)

experiment(2200, 18)
