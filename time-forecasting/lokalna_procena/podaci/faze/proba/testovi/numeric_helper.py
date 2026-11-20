def accumulate(length, width):
    total=0
    for row in range(length):
        for col in range(width):
            total += ((row*11+col)%113)*((row+col*5)%29)
    return total
