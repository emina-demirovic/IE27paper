import random

def sortiranje(n):
    rng = random.Random(42)
    niz = [rng.randrange(1_000_000) for _ in range(n)]
    niz.sort()
    return niz[0]

print(sortiranje(500_000))
