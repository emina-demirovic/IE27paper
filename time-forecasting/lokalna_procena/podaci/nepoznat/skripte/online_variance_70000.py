def online_variance(n, d):
    mean = total = 0.0
    for i in range(n):
        val = (i*13) % 503
        delta = val - mean
        mean += delta / (i+1)
        total += delta * (val-mean)
    return total / n

print(online_variance(70000, 24))
