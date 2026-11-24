"""Deterministic NumPy matrix multiplication workload for the IE27 dataset."""

import json
import sys


def run_matrix_multiplication(args):
    prefix, _, dimension = args.environment.strip().casefold().partition("-")
    if (
        args.simulate_failure or prefix != "matrix" or not dimension.isascii()
        or not dimension.isdecimal() or len(dimension) > 4
        or not 1 <= int(dimension) <= 2048 or args.max_steps < 1
    ):
        print("Expected matrix-<size> (1–2048) and positive repetitions.", file=sys.stderr)
        return 1

    import numpy as np

    size = int(dimension)
    rng = np.random.default_rng(args.seed % (2 ** 32))
    left = rng.random((size, size))
    right = rng.random((size, size))
    result = np.empty((size, size))
    for _ in range(args.max_steps):
        np.matmul(left, right, out=result)

    print("RESULT_JSON:" + json.dumps({
        "matrix_size": size,
        "repetitions": args.max_steps,
        "checksum": float(result[0, 0]),
    }))
    return 0
