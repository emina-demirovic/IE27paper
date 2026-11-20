class Metric:
    def evaluate(self,n,d):
        s=0
        for i in range(n):
            for j in range(d):
                s+=(i%11-j%7)*(i%11-j%7)
        return s

def run(n,d):
    metric=Metric()
    return metric.evaluate(n,d)

print(run(155000,36))
