def hamming_distance(n, d):
    acc = 0
    for i in range(n):
        for j in range(d):
            acc += ((i >> j) & 1) != ((i >> (j+1)) & 1)
    return acc

print(hamming_distance(120000, 32))
