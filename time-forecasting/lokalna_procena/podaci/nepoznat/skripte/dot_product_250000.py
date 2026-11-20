def dot_product(n, d):
    weights = [j/11 for j in range(d)]
    s = 0.0
    for i in range(n):
        for j in range(d):
            s += weights[j]*((i+j)%13)
    return s

print(dot_product(250000, 48))
