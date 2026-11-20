from pathlib import Path
import numpy as np
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import BaggingClassifier
from sklearn.model_selection import train_test_split

def read_table():
    dataset=np.loadtxt(Path(__file__).with_name("observations.csv"),delimiter=",")
    return dataset[:,:-1],dataset[:,-1]

def run(fraction):
    x,y=read_table()
    train,hold,labels,_=train_test_split(x,y,test_size=.3,random_state=5)
    forest=BaggingClassifier(estimator=DecisionTreeClassifier(max_depth=7),n_estimators=23,max_samples=fraction,random_state=5)
    forest.fit(train,labels)
    return forest.predict(hold)

print(run(0.3).shape)
