def prefix(values):
    out=[0]*(len(values)+1)
    for i in range(len(values)):
        out[i+1]=out[i]+values[i]
    return out

def evaluate(n):
    data=[(i*137)%997 for i in range(n)]
    acc=prefix(data)
    return sum(acc[i]-acc[i//2] for i in range(n))

print(evaluate(350000))
