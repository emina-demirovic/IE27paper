def zbir_kvadrata(n):
    zbir = 0
    for i in range(n):
        zbir += i * i
    return zbir

print(zbir_kvadrata(2_000_000))
