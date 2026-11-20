from sklearn.datasets import make_regression
from sklearn.linear_model import Ridge as Algorithm
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

def train(n,d,k,fraction):
    points,target=make_regression(n_samples=n,n_features=d,random_state=4)
    x,hold,y,_=train_test_split(points,target,test_size=.2,random_state=4)
    learner=make_pipeline(StandardScaler(), Algorithm(alpha=3))
    learner.fit(x,y)
    return learner.predict(hold)

print(train(13000,48,28,1.0).shape)
