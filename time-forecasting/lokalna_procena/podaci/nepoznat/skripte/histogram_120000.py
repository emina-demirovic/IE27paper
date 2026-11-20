def histogram(n, d):
    bins = [0]*d
    for i in range(n):
        bins[((i*479) % 1021)*d//1021] += 1
    return max(bins)

print(histogram(120000, 32))
