def one_hot(n, d):
    s = 0
    for i in range(n):
        v = [0]*d
        v[i%d] = 1
        s += sum(v)
    return s

print(one_hot(30000, 12))
