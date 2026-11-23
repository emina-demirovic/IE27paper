"""Worker entry point using the platform's existing Python executor protocol."""
import argparse
import ctypes as ct
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

SETUP = "From the repository root run: bash experiments/scheduling_v2/run.sh setup"


@contextmanager
def gemm(a, b, c, p):
    import numpy as np

    # An explicit OpenBLAS is useful with Accelerate-linked NumPy on macOS.
    # Pass the three NumPy buffers directly to one native row-major DGEMM.
    if path := os.environ.get("SCHED_V2_OPENBLAS"):
        lib = ct.CDLL(str(Path(path).resolve()))
        suffix = "" if hasattr(lib, "cblas_dgemm") else "64_"
        config = getattr(lib, "openblas_get_config" + suffix)
        config.restype = ct.c_char_p
        details = config().decode()
        dim = ct.c_int64 if "USE64BITINT" in details else ct.c_int
        setter = getattr(lib, "openblas_set_num_threads" + suffix)
        getter = getattr(lib, "openblas_get_num_threads" + suffix)
        setter.argtypes = [ct.c_int]
        setter.restype = None
        setter(p)
        multiply = getattr(lib, "cblas_dgemm" + suffix)
        ptr = ct.c_void_p
        multiply.argtypes = [ct.c_int] * 3 + [dim] * 3 + [ct.c_double, ptr, dim, ptr, dim,
                                                          ct.c_double, ptr, dim]
        multiply.restype = None
        n = len(a)
        args = (101, 111, 111, n, n, n, 1., a.ctypes.data, n, b.ctypes.data, n, 0., c.ctypes.data, n)
        yield lambda: multiply(*args), getter, {"backend": details, "library": str(Path(path).resolve()),
                                                "operation": "cblas_dgemm"}
        return

    from threadpoolctl import threadpool_info, threadpool_limits

    build = np.__config__.CONFIG["Build Dependencies"]["blas"]["name"].lower()
    with threadpool_limits(limits=p, user_api="blas"):
        def blas():
            return [x for x in threadpool_info() if x["user_api"] == "blas"]

        pools = blas()
        if len(pools) != 1 or pools[0]["internal_api"] not in build:
            raise RuntimeError(f"NumPy BLAS is {build!r}; cannot verify a matching thread pool: {pools}. {SETUP}")
        info = pools[0]
        yield lambda: np.matmul(a, b, out=c), lambda: blas()[0]["num_threads"], {
            "backend": f"{info['internal_api']} {info['version']}", "library": info["filepath"],
            "operation": "np.matmul"}


def run(n, r, seed, p, warmup=False):
    # Set startup limits before importing NumPy; the getter below is authoritative.
    for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = str(p)
    import numpy as np

    if n <= 0 or r <= 0 or p not in (1, 2, 4):
        raise ValueError("Expected positive N and R, and P in {1,2,4}.")
    rng = np.random.default_rng(seed)
    a = rng.random((n, n), dtype=np.float64)
    b = rng.random((n, n), dtype=np.float64)
    c = np.empty_like(a)
    with gemm(a, b, c, p) as (multiply, limit, backend):
        if limit() != p:
            raise RuntimeError(f"Requested P={p}, backend reports {limit()}. {SETUP}")
        warmup_s = 0.
        if warmup:  # Calibration only. Scheduled jobs do exactly R calls.
            start = time.perf_counter()
            multiply()
            warmup_s = time.perf_counter() - start
        start = time.perf_counter()
        for _ in range(r):
            multiply()
        seconds = time.perf_counter() - start
        verified = limit()
        if verified != p:
            raise RuntimeError(f"BLAS limit changed to {verified} during execution. {SETUP}")
    return dict(n=n, r=r, seed=seed, requested_p=p, verified_p=verified, compute_s=seconds,
                warmup_s=warmup_s, checksum=float(np.trace(c)), numpy=np.__version__, **backend)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id")
    parser.add_argument("--algorithm", choices=["numpy-dgemm"], required=True)
    parser.add_argument("--environment", required=True, help="N:P")
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()
    n, p = map(int, args.environment.split(":"))
    try:
        metrics = run(n, args.max_steps, args.seed, p, args.warmup)
        print("RESULT_JSON:" + json.dumps(metrics, allow_nan=False))
    except (ImportError, OSError, AttributeError, KeyError, RuntimeError) as exc:
        sys.exit(f"BLAS configuration error: {exc}\n{SETUP}")
