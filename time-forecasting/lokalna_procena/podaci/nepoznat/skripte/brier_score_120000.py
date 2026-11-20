def brier_score(n, d):
    error = 0.0
    for i in range(n):
        error += ((i % 101) / 100 - (i % 2)) ** 2
    return error / n

print(brier_score(120000, 32))
