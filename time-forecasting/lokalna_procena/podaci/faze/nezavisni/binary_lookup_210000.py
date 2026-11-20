def bisect_index(seq, target):
    low=0
    high=len(seq)
    while low<high:
        middle=(low+high)//2
        if seq[middle]<target:
            low=middle+1
        else:
            high=middle
    return low

def run(n):
    seq=list(range(n))
    total=0
    for i in range(n):
        total+=bisect_index(seq,(i*997)%n)
    return total

print(run(210000))
