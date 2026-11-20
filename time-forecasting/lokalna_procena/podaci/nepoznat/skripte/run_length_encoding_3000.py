def run_length_encoding(n, d):
    tokens = []
    last = None
    for i in range(n):
        v = (i//7)%d
        if v != last: tokens.append([v,1])
        else: tokens[-1][1] += 1
        last = v
    return len(tokens)

print(run_length_encoding(3000, 8))
