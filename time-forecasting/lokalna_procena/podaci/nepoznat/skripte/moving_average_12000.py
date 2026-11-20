def moving_average(n, d):
    window = [0]*d
    s = 0
    for i in range(n):
        k = i%d
        s -= window[k]
        window[k] = (i*29)%127
        s += window[k]
    return s/d

print(moving_average(12000, 16))
