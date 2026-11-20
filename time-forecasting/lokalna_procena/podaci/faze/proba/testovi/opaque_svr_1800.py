from sklearn.datasets import make_regression
from sklearn.svm import LinearSVR as Algorithm
from sklearn.model_selection import train_test_split

def train(n,d,k,fraction):
    points,target=make_regression(n_samples=n,n_features=d,random_state=4)
    x,hold,y,_=train_test_split(points,target,test_size=.2,random_state=4)
    learner=Algorithm(random_state=4, max_iter=150)
    learner.fit(x,y)
    return learner.predict(hold)

print(train(1800,14,9,0.4).shape)
