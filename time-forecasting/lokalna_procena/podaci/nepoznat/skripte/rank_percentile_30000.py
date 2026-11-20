def rank_percentile(n, d):
    values = [(i*997)%7919 for i in range(n)]
    values.sort()
    return values[9*n//10]

print(rank_percentile(30000, 12))
