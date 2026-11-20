def feature_hashing(n, d):
    counts = [0]*d
    for i in range(n):
        counts[(i*2654435761) % d] += 1 if i % 3 else -1
    return max(counts)

print(feature_hashing(12000, 16))
