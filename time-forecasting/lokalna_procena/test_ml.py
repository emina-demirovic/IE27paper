import json
import unittest
from pathlib import Path

from runtime_estimator import RuntimeEstimator, extract_args, fingerprint


class MLTests(unittest.TestCase):
    def test_static_parameters(self):
        code = 'def experiment(n, d, trees): pass\nexperiment(n=4000, d=30, trees=100)'
        self.assertEqual(extract_args(code), {'n': 4000, 'd': 30, 'trees': 100})

    def test_saved_experiment_has_no_test_leakage(self):
        root = Path(__file__).parent
        data = root / 'podaci/ml'
        if not (data / 'rezultati.json').exists():
            self.skipTest('Prvo pokrenite demonstracija_ml.py')
        estimator = RuntimeEstimator(data / 'kalibracija.json')
        plan = json.loads((data / 'plan.json').read_text())
        self.assertEqual(len(estimator.records), 48)
        self.assertEqual(estimator.model['training_configurations'], 16)
        trained_algorithms = {c['algorithm'] for c in plan['training']}
        unseen = {c['algorithm'] for c in plan['tests'] if c['scenario'] == 'neviđen algoritam'}
        self.assertTrue(trained_algorithms.isdisjoint(unseen))
        self.assertEqual(len(unseen), 7)
        before = json.loads((data / 'procene_pre_testova.json').read_text())
        after = json.loads((data / 'rezultati.json').read_text())
        self.assertEqual(len(after), len(plan['tests']))
        trained_keys = {r['fingerprint'] for r in estimator.records}
        for prediction, result in zip(before, after):
            self.assertNotIn('merenja_s', prediction)
            self.assertEqual(prediction['config'], result['config'])
            self.assertEqual(prediction['procena_s'], result['procena_s'])
            self.assertEqual(len(result['merenja_s']), 5)
            source = (root / 'primeri_ml' / (prediction['config']['name'] + '.py')).read_text()
            self.assertNotIn(fingerprint(source), trained_keys)
            seconds, mode = estimator.estimate(source)
            self.assertEqual(mode, 'model')
            self.assertEqual(seconds, prediction['procena_s'])

    def test_large_unseen_experiments(self):
        root = Path(__file__).parent
        data = root / 'podaci/ml'
        if not (data / 'teski_rezultati.json').exists():
            self.skipTest('Prvo pokrenite demonstracija_ml_teski.py')
        estimator = RuntimeEstimator(data / 'kalibracija.json')
        before = json.loads((data / 'teski_procene_pre_testova.json').read_text())
        after = json.loads((data / 'teski_rezultati.json').read_text())
        self.assertEqual(len(after), 2)
        for prediction, result in zip(before, after):
            self.assertNotIn('merenja_s', prediction)
            self.assertEqual(prediction['procena_s'], result['procena_s'])
            self.assertEqual(len(result['merenja_s']), 5)
            source = (root / 'primeri_ml' / (prediction['config']['name'] + '.py')).read_text()
            self.assertEqual(estimator.estimate(source), (prediction['procena_s'], 'model'))


if __name__ == '__main__':
    unittest.main()
