"""Exercises the exact SQL installed in the V2 coordinator's private database."""
import collections
import concurrent.futures
import heapq
import itertools
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

from calibration import CLASSES, MIX, ROOT, make_manifest
from experiment import export, verify_checksums

CAL = {"mode": "full", "backend": {}, "classes":
       {c: {"n": 32*(i+1), "r": i+1, "k": i+1} for i, c in enumerate(CLASSES)}}


def connect(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=10)
    db.create_function("v2_ticks", 0, time.monotonic_ns)
    return db


def populate(db, jobs, constrained):
    db.execute("""CREATE TABLE Experiments(Id TEXT PRIMARY KEY, Name TEXT NOT NULL, Status INTEGER DEFAULT 0,
                  AssignedWorkerId TEXT, Attempt INTEGER DEFAULT 0)""")
    db.executescript((ROOT / "admission.sql").read_text())
    db.execute("INSERT INTO v2_config VALUES(10,?)", (int(constrained),))
    for i, (k, p) in enumerate(jobs):
        name = str(i)
        db.execute("INSERT INTO v2_tasks VALUES(?,?,?,?)", (name, i, k, p))
        db.execute("INSERT INTO Experiments(Id,Name) VALUES(?,?)", (name, name))


def next_id(db):
    return db.execute("SELECT Id FROM v2_next").fetchone()


def assign(db, task, worker):
    return db.execute("""UPDATE Experiments SET Status=1, AssignedWorkerId=?, Attempt=Attempt+1
                         WHERE Id=? AND Status=0""", (worker, task)).rowcount


class SchedulingTests(unittest.TestCase):
    def test_control_manifest_and_identical_order(self):
        manifest = make_manifest(CAL, "frozen")
        self.assertEqual(manifest, make_manifest(CAL, "frozen"))
        jobs = manifest["jobs"]
        counts = collections.Counter((j["workload_class"], j["p"]) for j in jobs)
        self.assertEqual([[counts[c,p] for p in (1,2,4)] for c in CLASSES], list(map(list, MIX)))
        control = make_manifest(CAL, "frozen", True)["jobs"]
        self.assertEqual(control, [dict(j, p=1) for j in jobs])
        orders = []
        for constrained in (False, True):
            with closing(connect(":memory:")) as db:
                populate(db, [(j["k"], 1) for j in control], constrained)
                available = [(0, w, "") for w in range(10)]
                trace = []
                for _ in jobs:
                    when, worker, done = heapq.heappop(available)
                    db.execute("UPDATE Experiments SET Status=2 WHERE Id=?", (done,))
                    task, = next_id(db)
                    self.assertEqual(assign(db, task, str(worker)), 1)
                    trace.append(int(task))
                    heapq.heappush(available, (when+control[int(task)]["k"], worker, task))
                orders.append(trace)
        expected = sorted(range(115), key=lambda i: (-control[i]["k"], i))
        self.assertEqual(orders, [expected, expected])

    def test_fit_atomic_rollback_and_attempt_end(self):
        with closing(connect(":memory:")) as db:
            populate(db, [(10,4), (9,4), (8,4), (7,2), (6,1)], True)
            db.execute("BEGIN IMMEDIATE")
            self.assertEqual(assign(db, "0", "w0"), 1)
            db.rollback()
            self.assertEqual(db.execute("SELECT count(*) FROM v2_events").fetchone(), (0,))
            self.assertEqual(assign(db, "0", "w0"), 1)
            self.assertEqual(assign(db, "1", "w0"), 0)
            self.assertEqual(assign(db, "1", "w1"), 1)
            self.assertEqual(next_id(db), ("3",))  # skip P=4 with two units left
            self.assertEqual(assign(db, "3", "w3"), 1)
            self.assertIsNone(next_id(db))
            for task, end in [("0", 3), ("1", 4), ("3", 0)]:  # failed, cancelled, requeued
                db.execute("UPDATE Experiments SET Status=? WHERE Id=? AND Status=1", (end, task))
                db.execute("UPDATE Experiments SET Status=? WHERE Id=? AND Status=1", (end, task))
            self.assertEqual(db.execute("SELECT reserved FROM v2_load").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT count(*) FROM v2_events WHERE delta<0").fetchone(), (3,))
            self.assertEqual(assign(db, "2", "w2"), 1)
            self.assertEqual(assign(db, "3", "w3"), 1)
            self.assertEqual(db.execute("SELECT attempt FROM v2_events WHERE task='3' ORDER BY seq DESC LIMIT 1")
                             .fetchone(), (2,))

    def test_simultaneous_workers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "db"
            with closing(connect(path)) as db:
                populate(db, [(1, 4)] * 20, True)
                barrier = threading.Barrier(10)
                def request(i):
                    with closing(connect(path)) as conn:
                        first, = next_id(conn)
                        barrier.wait(timeout=10)
                        # All ten callers have observed the SAME first candidate.
                        for _ in range(10):
                            if assign(conn, first, str(i)):
                                return True
                            nxt = next_id(conn)
                            if nxt is None:
                                return False
                            first, = nxt
                        return False
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                    self.assertEqual(sum(pool.map(request, range(10))), 2)
                self.assertEqual(db.execute("SELECT reserved FROM v2_load").fetchone(), (8,))
                deltas = (r[0] for r in db.execute("SELECT delta FROM v2_events ORDER BY seq"))
                self.assertLessEqual(max(itertools.accumulate(deltas)), 10)

    def test_accounting_and_exactly_once(self):
        backend = dict(backend="fixture", library="fixture", operation="fixture", numpy="fixture")
        jobs = [dict(task_id=str(i), arrival_index=i, n=16, r=2, seed=i, k=2-i, p=4) for i in range(2)]
        manifest = dict(jobs=jobs, backend=backend)
        tasks = [dict(task_id=j["task_id"], experiment_id=j["task_id"], worker_id=j["task_id"],
                      status="Completed", attempt=1, completion_s=t, process_ms=50,
                      metrics=dict(n=16, r=2, seed=j["seed"], requested_p=4, verified_p=4, warmup_s=0,
                                   compute_s=.1, checksum=123., **backend)) for j, t in zip(jobs, (2.9, 4.5))]
        events = [dict(worker_id=j, task_id=j, attempt=1, time_s=t, delta=p) for j, t, p in
                  [("0", 1., 4), ("1", 2., 4), ("0", 3., -4), ("1", 5., -4)]]
        raw = dict(tasks=tasks, events=events, workers=["0", "1"], policy="LPT-K", budget=4, manifest_id="test")
        with tempfile.TemporaryDirectory() as directory:
            summary, checksums = export(raw, manifest, "test", Path(directory))
            self.assertEqual(summary["peak_reserved_p"], 8)
            self.assertEqual(summary["fraction_over_budget"], 1/4.5)
            self.assertEqual(summary["makespan_s"], 4.5)
            self.assertEqual(summary["completed_tasks"], 2)
            verify_checksums(checksums, {"0": 123.+1e-12, "1": 123.})
            with self.assertRaisesRegex(ValueError, "checksums"):
                verify_checksums(checksums, {"0": 125., "1": 123.})
            for bad in ([tasks[0]], [tasks[1], tasks[1]]):
                with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
                    export(dict(raw, tasks=bad), manifest, "bad", Path(directory))

    def test_dense_product(self):
        import numpy as np
        from matrix_job import run
        rng = np.random.default_rng(198)
        a, b = rng.random((48, 48)), rng.random((48, 48))
        reference = np.einsum("ij,ji->", a, b, optimize=False)
        for p in (1, 2, 4):
            row = run(48, 3, 198, p)
            self.assertEqual(row["verified_p"], p)
            self.assertAlmostEqual(row["checksum"], reference, places=8)


if __name__ == "__main__":
    unittest.main()
