import json, statistics, math

# Numpy
for machine in ['gleb-devkit-arm64', 'gleb-surface-15-arm64']:
    for tc in ['llvm', 'msvc']:
        path = f'results/{machine}/numpy/numpy_{tc}_arm64.json'
        with open(path) as f:
            d = json.load(f)
        times = d['times_sec']
        print(f'{machine} numpy {tc}: mean={statistics.mean(times):.7f} median={statistics.median(times):.7f}')

print()

# CPython - extract benchmark geometric means
for machine in ['gleb-devkit-arm64', 'gleb-surface-15-arm64']:
    for tc in ['llvm', 'msvc']:
        path = f'results/{machine}/cpython/pyperformance_{tc}_arm64.json'
        with open(path) as f:
            d = json.load(f)
        bench_means = []
        for b in d['benchmarks']:
            name = b['metadata']['name']
            values = []
            for run in b['runs']:
                if 'values' in run:
                    values.extend(run['values'])
            if values:
                mean_val = statistics.mean(values)
                bench_means.append((name, mean_val))
        print(f'{machine} cpython {tc}:')
        for name, val in bench_means:
            print(f'  {name}: {val:.6f}')
        geo = math.exp(sum(math.log(v) for _, v in bench_means) / len(bench_means))
        print(f'  GEOMETRIC MEAN: {geo:.6f}')
    print()
