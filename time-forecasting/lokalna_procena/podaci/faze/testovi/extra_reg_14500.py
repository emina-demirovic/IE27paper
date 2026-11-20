from sklearn.datasets import make_regression
from sklearn.ensemble import ExtraTreesRegressor as Algorithm
from sklearn.model_selection import train_test_split

def train(n,d,k,fraction):
    points,target=make_regression(n_samples=n,n_features=d,random_state=4)
    x,hold,y,_=train_test_split(points,target,test_size=.2,random_state=4)
    learner=Algorithm(n_estimators=k, max_depth=10, random_state=4)
    learner.fit(x,y)
    return learner.predict(hold)

print(train(14500,44,30,0.95).shape)
