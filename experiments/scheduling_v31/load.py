"""One independent POSIX process group. stdin EOF from the driver stops the group."""
import os
import select
import signal
import sys
import time
from pathlib import Path


def burner(gate, condition, phase):
    while True:
        try:
            start = float(gate.read_text())
            break
        except FileNotFoundError:
            time.sleep(.002)
    value = 1
    while True:
        elapsed = time.monotonic() - start
        if condition == "steady" or int(elapsed / phase) % 2 == 1:
            for _ in range(20000):
                value = (1664525 * value + 1013904223) & 0xffffffff
        else:
            time.sleep(min(.02, phase - elapsed % phase))


def main():
    condition, gate, phase = sys.argv[1:]
    children = []
    try:
        for _ in range(3 if condition == "steady" else 4):
            pid = os.fork()
            if pid == 0:
                try:
                    burner(Path(gate), condition, float(phase))
                finally:
                    os._exit(1)
            children.append(pid)
        print("ready", flush=True)
        while not select.select([sys.stdin], [], [], .2)[0]:
            exited, _ = os.waitpid(-1, os.WNOHANG)
            if exited:
                children.remove(exited)
                raise RuntimeError("Load process exited before the run ended")
    finally:
        for pid in children:
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            except (ChildProcessError, ProcessLookupError):
                pass


if __name__ == "__main__":
    main()
