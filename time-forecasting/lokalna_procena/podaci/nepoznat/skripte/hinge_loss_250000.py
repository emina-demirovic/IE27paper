def hinge_loss(n, d):
    bad = 0.0
    for i in range(n):
        margin = ((i * 37) % 257 - 128) / 64
        bad += max(0, 1 - margin)
    return bad / n

print(hinge_loss(250000, 48))
