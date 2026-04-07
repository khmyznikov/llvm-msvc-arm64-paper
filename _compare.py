import json, statistics, math

results = {}
for tc in ('msvc', 'llvm'):
    path = f'results/gleb-devkit-arm64/cpython/pyperformance_{tc}_arm64.json'
    with open(path) as f:
        d = json.load(f)
    means = {}
    for b in d['benchmarks']:
        name = b['metadata']['name']
        values = []
        for run in b['runs']:
            if 'values' in run:
                values.extend(run['values'])
        if values:
            means[name] = statistics.mean(values)
    results[tc] = means

print(f"{'Benchmark':30s} {'MSVC (ms)':>12s} {'LLVM (ms)':>12s} {'LLVM faster':>12s}")
print('-' * 70)
bench_names = sorted(results['msvc'].keys())
for name in bench_names:
    msvc_v = results['msvc'].get(name, 0)
    llvm_v = results['llvm'].get(name, 0)
    if msvc_v > 0:
        pct = (msvc_v - llvm_v) / msvc_v * 100
        print(f'{name:30s} {msvc_v*1000:12.3f} {llvm_v*1000:12.3f} {pct:+11.1f}%')

# Geo means
msvc_geo = math.exp(sum(math.log(v) for v in results['msvc'].values()) / len(results['msvc']))
llvm_geo = math.exp(sum(math.log(v) for v in results['llvm'].values()) / len(results['llvm']))
pct = (msvc_geo - llvm_geo) / msvc_geo * 100
print('-' * 70)
print(f"{'GEOMETRIC MEAN':30s} {msvc_geo*1000:12.3f} {llvm_geo*1000:12.3f} {pct:+11.1f}%")
print(f'Benchmarks: {len(results["msvc"])} MSVC, {len(results["llvm"])} LLVM')
