def run(n,d):
    buf=[0]*d
    for i in range(n):
        idx=(i*17)%d
        buf[idx]+=i%19
    return sum(buf)

print(run(125000,32))
