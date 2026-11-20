from math import log
def log_loss(n, d):
    acc = 0.0
    for i in range(n):
        prob = ((i%99)+1)/101
        acc -= log(prob if i%2 else 1-prob)
    return acc/n

print(log_loss(70000, 24))
