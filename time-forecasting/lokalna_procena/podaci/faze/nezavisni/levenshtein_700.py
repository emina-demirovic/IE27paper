def distance(n):
    left=[(i*7)%17 for i in range(n)]
    right=[(i*3)%13 for i in range(n)]
    previous=list(range(n+1))
    for i in range(n):
        current=[i+1]*(n+1)
        for j in range(n):
            current[j+1]=min(current[j]+1,previous[j+1]+1,previous[j]+(left[i]!=right[j]))
        previous=current
    return previous[-1]

print(distance(700))
