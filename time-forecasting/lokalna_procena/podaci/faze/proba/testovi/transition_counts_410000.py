def run(n,d):
    counts={}
    for i in range(n):
        key=(i*13)%d
        counts[key]=counts.get(key,0)+1
    return len(counts)

print(run(410000,64))
