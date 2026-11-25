"""Check the Darwin counter across a complete between-samples process tree."""
import ctypes
import os
import resource
import time
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "scheduling_v2/bin/Debug/net10.0/libv31cpu.dylib"


def work_seconds():
    read = ctypes.CDLL(str(LIB)).v31_counters
    host, work, load = (ctypes.c_double() for _ in range(3))
    if read(0, ctypes.byref(host), ctypes.byref(work), ctypes.byref(load)) != 0:
        raise RuntimeError("Darwin counters unavailable")
    return work.value


class NativeCounters(unittest.TestCase):
    def test_reaped_child_and_grandchild(self):
        start = work_seconds()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        pid = os.fork()
        if pid == 0:
            grandchild = os.fork()
            if grandchild == 0:
                deadline = time.process_time() + .08
                while time.process_time() < deadline:
                    pass
                os._exit(0)
            _, status = os.waitpid(grandchild, 0)
            os._exit(os.waitstatus_to_exitcode(status))
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        busy = work_seconds() - start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        expected = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
        self.assertGreater(busy, .075)
        self.assertAlmostEqual(busy, expected, delta=.005)


if __name__ == "__main__":
    unittest.main()
