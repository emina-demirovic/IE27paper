from sklearn.datasets import make_blobs
from sklearn.ensemble import IsolationForest as Algorithm
from sklearn.model_selection import train_test_split

def train(n,d,k,fraction):
    points,target=make_blobs(n_samples=n,n_features=d,random_state=4)
    x,hold,y,_=train_test_split(points,target,test_size=.2,random_state=4)
    learner=Algorithm(n_estimators=k, random_state=4)
    learner.fit(x,y)
    return learner.predict(hold)

print(train(7200,28,18,0.65).shape)
