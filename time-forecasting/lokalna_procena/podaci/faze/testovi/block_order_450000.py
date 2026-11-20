def run(n,d):
    scores=[(idx*9973)%50021 for idx in range(n)]
    scores.sort()
    return scores[n//2]

print(run(450000,62))
