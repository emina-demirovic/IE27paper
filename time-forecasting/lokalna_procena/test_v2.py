import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from demonstracija_v2 import plan, source
from ml_v2 import profile, predict
from runtime_estimator import fingerprint

ROOT = Path(__file__).resolve().parent


class StaticProfileTests(unittest.TestCase):
    def test_unused_parameters_do_not_change_profile(self):
        training, _ = plan()
        c = training[0]
        self.assertEqual(profile(source(c)), profile(source({**c, 'trees': 999, 'clusters': 900})))

    def test_actual_constructor_and_loops(self):
        training, _ = plan()
        forest = next(c for c in training if c['algorithm'] == 'forest')
        basic = profile(source(forest))
        more_trees = profile(source({**forest, 'trees': forest['trees']*4}))
        self.assertAlmostEqual(more_trees['work']/basic['work'], 4)
        repeated = profile(source({**forest, 'repeats': 3}))
        self.assertAlmostEqual(repeated['work']/basic['work'], 3)
        cv = profile(source({**forest, 'folds': 5}))
        self.assertEqual(cv['jobs'], 5)

    def test_alias_constants_and_main_guard(self):
        text = '''from sklearn.svm import SVC as Classifier
from sklearn.datasets import make_classification as data
N = 4000
def run(n, d=20):
    x, y = data(n_samples=n, n_features=d)
    model = Classifier(C=2)
    model.fit(x, y)
if __name__ == '__main__':
    run(N, 30)
'''
        p = profile(text)
        self.assertEqual((p['family'], p['n'], p['d']), ('svm', 4000, 30))
        self.assertEqual(p['parameters']['C'], 2)

    def test_dynamic_code_is_not_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder)/'executed'
            text = f'''from pathlib import Path
from sklearn.datasets import make_classification
from sklearn.svm import SVC
def run():
    x, y = make_classification(n_samples=Path({str(marker)!r}).touch(), n_features=20)
    SVC().fit(x, y)
run()
'''
            self.assertFalse(profile(text)['supported'])
            self.assertFalse(marker.exists())


class ExperimentTests(unittest.TestCase):
    def test_final_holdouts_and_family_exclusion(self):
        data = ROOT/'podaci/v2'
        if not (data/'rezultati.json').exists():
            self.skipTest('Prvo pokrenite demonstracija_v2.py')
        plan_data = json.loads((data/'plan.json').read_text())
        calibration = json.loads((data/'kalibracija.json').read_text())
        folds = json.loads((data/'fold_models.json').read_text())
        before = json.loads((data/'procene_pre_testova.json').read_text())
        after = json.loads((data/'rezultati.json').read_text())
        self.assertEqual(len(after), 17)
        self.assertEqual(len(calibration['measurements']), 46*3)
        self.assertEqual({r['config']['name'] for r in after}, {c['name'] for c in plan_data['tests']})
        family_for = {c['name']: c['algorithm'] for c in plan_data['training']}
        for family, fold in folds.items():
            self.assertTrue(all(family_for[name] != family for name in fold['training_names']))
            self.assertNotIn(family, fold['model']['families'])
        keys = {r['fingerprint'] for r in calibration['measurements']}
        for frozen, result in zip(before, after):
            self.assertNotIn('actual', frozen)
            self.assertEqual(frozen['lofo'], result['lofo'])
            self.assertEqual(frozen['known'], result['known'])
            self.assertEqual(len(result['durations']), 5)
            text = (ROOT/'primeri_v2'/(result['config']['name']+'.py')).read_text()
            self.assertNotIn(fingerprint(text), keys)
            family = result['config']['algorithm']
            predicted = predict(folds[family]['model'], text)
            self.assertEqual(predicted, frozen['lofo'])
            self.assertEqual(predicted['confidence'], 'low')
            self.assertTrue(math.isfinite(predicted['upper_s']))

    def test_cli_json_and_numeric_output(self):
        database = ROOT/'podaci/v2/kalibracija.json'
        if not database.exists():
            self.skipTest('Prvo pokrenite demonstracija_v2.py')
        command = [sys.executable, str(ROOT/'proceni.py'), str(ROOT/'primeri_v2/test_svm_veci.py'), '--baza', str(database)]
        number = subprocess.run(command, capture_output=True, text=True, check=True)
        details = subprocess.run(command+['--detalji'], capture_output=True, text=True, check=True)
        self.assertRegex(number.stdout, r'^\d+\.\d+\n$')
        self.assertEqual(number.stderr, '')
        self.assertAlmostEqual(float(number.stdout), json.loads(details.stdout)['seconds'], places=5)


if __name__ == '__main__':
    unittest.main()
