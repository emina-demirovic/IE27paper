def run(n,d):
    total=0
    for i in range(n):
        cell=[0]*d
        cell[i%d]=1
        total+=cell[i%d]
    return total

print(run(155000,36))
