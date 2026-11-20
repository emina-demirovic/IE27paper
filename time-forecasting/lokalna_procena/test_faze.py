"""Regresije pri statičkoj analizi korisničke skripte."""
import tempfile
import unittest
from pathlib import Path

from faze_model import predict


MODEL = dict(startup=.01, imports=.7, numpy_import=.03, ops={'loop':.001},
             tree=1e-8, extra=1e-8, linear=1e-8)


class PhaseTests(unittest.TestCase):
    def test_local_helper_analyzed_without_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            marker=folder/'ran'
            (folder/'helper.py').write_text(f"""
from pathlib import Path
Path({str(marker)!r}).touch()
def helper(n):
    for i in range(n):
        pass
""")
            code='from helper import helper as run\nrun(12)\n'
            result=predict(MODEL,code,folder/'main.py')
            self.assertFalse(marker.exists())
            self.assertEqual(result['work']['loop'],12)

    def test_hidden_model_uses_all_columns_and_marks_unknown(self):
        src="""
from sklearn.datasets import make_classification
from sklearn.svm import LinearSVR
x,y=make_classification(n_samples=700,n_features=24)
LinearSVR().fit(x,y)
"""
        result=predict(MODEL,src)
        self.assertEqual(result['fits'][0]['features_per_split_or_fit'],24)
        self.assertIn('Nepoznat trošak fit: LinearSVR',result['unresolved'])

    def test_ensemble_effective_sample_and_base(self):
        src="""
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
from sklearn.ensemble import IsolationForest, BaggingClassifier
from sklearn.tree import DecisionTreeClassifier
x,y=make_classification(n_samples=2000,n_features=24)
a,b,c,d=train_test_split(x,y,test_size=0.25)
IsolationForest(n_estimators=12).fit(a)
BaggingClassifier(estimator=DecisionTreeClassifier(max_depth=3),n_estimators=8,max_samples=0.4,max_features=0.5).fit(a,c)
"""
        isolation,bag=predict(MODEL,src)['fits']
        self.assertEqual(isolation['samples_per_member'],256)
        self.assertEqual((bag['samples_per_member'],bag['features_per_split_or_fit'],bag['members']),(600,12,8))
        self.assertEqual(bag['base'],'DecisionTreeClassifier')
