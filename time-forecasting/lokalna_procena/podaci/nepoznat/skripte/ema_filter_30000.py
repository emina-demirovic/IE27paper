def ema_filter(n, d):
    acc = 0.0
    for i in range(n):
        acc = 0.97*acc + 0.03*((i*19)%101)
    return acc

print(ema_filter(30000, 12))
