def confusion_matrix(n, d):
    counts = [[0]*d for _ in range(d)]
    for i in range(n):
        counts[i % d][(i * 7 // 3) % d] += 1
    return counts[0][0]

print(confusion_matrix(3000, 8))
