from random import Random
def reservoir_sampling(n, d):
    rng = Random(13)
    sample = list(range(d))
    for i in range(d,n):
        j = rng.randrange(i+1)
        if j < d: sample[j] = i
    return sample[0]

print(reservoir_sampling(3000, 8))
