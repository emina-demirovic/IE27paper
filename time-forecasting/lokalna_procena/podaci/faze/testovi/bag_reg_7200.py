from sklearn.datasets import make_regression
from sklearn.ensemble import BaggingRegressor as Algorithm
from sklearn.model_selection import train_test_split

def train(n,d,k,fraction):
    points,target=make_regression(n_samples=n,n_features=d,random_state=4)
    x,hold,y,_=train_test_split(points,target,test_size=.2,random_state=4)
    learner=Algorithm(n_estimators=k, max_samples=fraction, max_features=0.75, random_state=4)
    learner.fit(x,y)
    return learner.predict(hold)

print(train(7200,28,18,0.65).shape)
