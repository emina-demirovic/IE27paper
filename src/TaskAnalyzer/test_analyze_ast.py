"""CLI tests that analyze committed source without importing target programs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ANALYZER = Path(__file__).resolve().with_name("analyze_ast.py")
REPOSITORY = ANALYZER.parents[2]
WORKLOADS = "src/Worker/Scripts/"


class TaskAnalyzerTests(unittest.TestCase):
    def analyze(self, repository, entry_point, *options):
        result = subprocess.run(
            [
                sys.executable, str(ANALYZER), "--repository", str(repository),
                "--commit", "HEAD", "--entry-point", entry_point, *options,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["task"]["entryPoint"], entry_point)
        self.assertTrue(report["task"]["gitCommit"])
        return report

    def test_existing_random_forest(self):
        report = self.analyze(
            REPOSITORY, WORKLOADS + "classical_ml.py", "--arg", "max-steps=100"
        )["features"]
        self.assertEqual(report["known"]["arguments"]["max-steps"], 100)
        self.assertGreater(report["derived"]["ast"]["entryPoint"]["callCount"], 0)
        calls = report["derived"]["callsByFile"][WORKLOADS + "classical_ml.py"]
        self.assertIn("sklearn.ensemble.RandomForestClassifier", calls["imports"])
        self.assertEqual(calls["libraryCallCounts"]["sklearn.model_selection.train_test_split"], 1)

    def test_existing_rl_dispatcher_and_workload(self):
        entry = WORKLOADS + "run_experiment.py"
        workload = WORKLOADS + "rl_workloads.py"
        report = self.analyze(REPOSITORY, entry, "--arg", "algorithm=q-learning-discrete")
        self.assertIn(workload, report["coverage"]["scannedFiles"])
        features = report["features"]
        self.assertEqual(
            features["unavailable"]["source.dynamicImportTargets"], "not_resolved_statically"
        )
        self.assertGreater(features["derived"]["ast"]["localModules"][workload]["forCount"], 0)
        calls = features["derived"]["callsByFile"][workload]
        self.assertIn("gymnasium", calls["imports"])
        self.assertEqual(calls["libraryCallCounts"]["gymnasium.make"], 1)
        self.assertIn(["1", "max_steps + 1"], [item["arguments"] for item in calls["rangeCalls"]])

    def test_numeric_program_is_read_from_commit_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            source = repository / "numeric.py"
            source.write_text(
                'import math\n'
                'raise RuntimeError("analysis must not execute this file")\n'
                'def score(repeats, scale):\n'
                '    total = 0\n'
                '    for index in range(repeats):\n'
                '        total += math.sqrt(index * scale) / 2\n'
                '    return total ** 2\n',
                encoding="utf-8",
            )

            def git(*arguments):
                subprocess.run(
                    ["git", "-C", directory, *arguments], check=True, capture_output=True
                )

            git("init", "--quiet")
            git("add", source.name)
            git(
                "-c", "user.name=Analyzer Tests",
                "-c", "user.email=analyzer@example.invalid",
                "-c", "commit.gpgsign=false",
                "-c", "core.hooksPath=.git/no-hooks",
                "commit", "--quiet", "-m", "Numeric test source",
            )
            source.write_text("pass\n", encoding="utf-8")
            features = self.analyze(
                repository, source.name,
                "--arg", "repeats=4", "--arg", "scale=1.5",
                "--input", f"data={repository / 'missing.npy'}",
            )["features"]

        self.assertEqual(features["known"]["arguments"], {"repeats": 4, "scale": 1.5})
        self.assertEqual(features["unavailable"]["inputs.data"], "file_not_found")
        self.assertEqual(features["derived"]["callsByFile"]["numeric.py"]["imports"], ["math"])
        structure = features["derived"]["ast"]["entryPoint"]
        self.assertEqual(structure["forCount"], 1)
        self.assertEqual(structure["callCount"], 3)
        for operator in ("add", "multiply", "divide", "power"):
            self.assertEqual(structure["arithmeticOperatorCounts"][operator], 1)
        self.assertEqual(structure["arithmeticOperatorCounts"]["matrixMultiply"], 0)


if __name__ == "__main__":
    unittest.main()
