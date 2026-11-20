def l1_distance(n, d):
    out = 0
    for i in range(n):
        for j in range(d):
            out += abs((i+j)%17 - (j*5)%11)
    return out

print(l1_distance(250000, 48))
