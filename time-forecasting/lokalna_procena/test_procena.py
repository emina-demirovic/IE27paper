import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from runtime_estimator import RuntimeEstimator, extract_args, fingerprint


class EstimatorTests(unittest.TestCase):
    def test_modes_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.json'
            estimator = RuntimeEstimator(path)
            code = 'def f(n):\n    return n*n\nf(50)\n'
            self.assertEqual(estimator.estimate(code), (1.0, 'default'))
            for duration in [0.03, 0.01, 0.02, 0.09, 0.04]:
                estimator.record(code, duration)
            comments = code + '# a\n# b\n# c\n# d\n'
            self.assertEqual(fingerprint(code), fingerprint(comments))
            self.assertEqual(estimator.estimate(comments), (0.03, 'measured'))
            estimator.record(code.replace('f(50)', 'f(100)'), 0.05)
            estimator.fit()
            estimator.save()
            loaded = RuntimeEstimator(path)
            seconds, mode = loaded.estimate(code.replace('f(50)', 'f(75)'))
            self.assertEqual(mode, 'model')
            self.assertAlmostEqual(seconds, 0.04)

    def test_literal_args(self):
        self.assertEqual(extract_args('def f(n): pass\nprint(f(2_000_000))'), {'n': 2_000_000})
        self.assertEqual(extract_args('def f(n): pass\nf(n=500_000)'), {'n': 500_000})
        self.assertEqual(extract_args('def f(n): pass\nf(dangerous())'), {})

    def test_cli_does_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'executed'
            script = Path(directory) / 'script.py'
            script.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n'
                              'raise RuntimeError("MUST NOT RUN")\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(Path(__file__).parent / 'proceni.py'),
                                     str(script)], capture_output=True, text=True, check=True)
            self.assertRegex(result.stdout, r'^\d+\.\d+\n$')
            self.assertEqual(result.stderr, '')
            self.assertFalse(marker.exists())

    def test_demo_artifacts(self):
        data = Path(__file__).parent / 'podaci'
        if not (data / 'rezultati.json').exists():
            self.skipTest('Prvo pokrenite demonstracija.py')
        rows = json.loads((data / 'rezultati.json').read_text())['rezultati']
        self.assertEqual([r['rezim'] for r in rows],
                         ['default', 'measured', 'measured', 'model', 'model'])
        calibration = json.loads((data / 'kalibracija.json').read_text())
        self.assertEqual(len(calibration['measurements']), 20)
        self.assertEqual(calibration['model']['training_configurations'], 5)
        before = json.loads((data / 'procene_pre_C.json').read_text())
        for prediction, result in zip(before, rows[-2:]):
            self.assertNotIn('merenja_s', prediction)
            self.assertEqual(prediction['procena_s'], result['procena_s'])
        self.assertTrue(all(len(row['merenja_s']) == 5 for row in rows))
        for name in ['zbir.py', 'sortiranje.py']:
            source = (data.parent / 'primeri' / name).read_text()
            self.assertNotIn(fingerprint(source),
                             [r['fingerprint'] for r in calibration['measurements']])


if __name__ == '__main__':
    unittest.main()
