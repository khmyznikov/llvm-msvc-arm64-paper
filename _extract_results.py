import json, statistics, math

mid = 'gleb-devkit-arm64'
base = f'results/{mid}'

# LAME
for tc in ('msvc', 'llvm'):
    d = json.load(open(f'{base}/lame/lame_{tc}_arm64.json'))
    print(f'LAME {tc}: mean={d["mean_sec"]:.3f}s min={d["min_sec"]:.3f}s max={d["max_sec"]:.3f}s')

# NumPy
for tc in ('msvc', 'llvm'):
    d = json.load(open(f'{base}/numpy/numpy_{tc}_arm64.json'))
    for op, data in d['operations'].items():
        print(f'NumPy {op} {tc}: mean={data["mean_sec"]*1000:.3f}ms min={data["min_sec"]*1000:.3f}ms max={data["max_sec"]*1000:.3f}ms')

# x264
d = json.load(open(f'{base}/x264/x264_results_arm64.json'))
for tc in ('msvc', 'llvm'):
    r = d['results'][tc]
    print(f'x264 {tc}: mean_fps={r["mean_fps"]:.2f} min={r["min_fps"]:.2f} max={r["max_fps"]:.2f}')

# CPython
for tc in ('msvc', 'llvm'):
    d = json.load(open(f'{base}/cpython/pyperformance_{tc}_arm64.json'))
    means = {}
    for b in d['benchmarks']:
        name = b['metadata']['name']
        values = []
        for run in b['runs']:
            if 'values' in run:
                values.extend(run['values'])
        if values:
            means[name] = statistics.mean(values)
    geo = math.exp(sum(math.log(v) for v in means.values()) / len(means))
    print(f'CPython {tc} geo-mean: {geo*1000:.2f}ms')
    for name in sorted(means):
        print(f'  {name}: {means[name]*1000:.2f}ms')

# LAME advantage
msvc = json.load(open(f'{base}/lame/lame_msvc_arm64.json'))['mean_sec']
llvm = json.load(open(f'{base}/lame/lame_llvm_arm64.json'))['mean_sec']
print(f'\nLAME advantage: {(msvc-llvm)/msvc*100:.1f}%')

# x264 advantage
d = json.load(open(f'{base}/x264/x264_results_arm64.json'))
msvc_fps = d['results']['msvc']['mean_fps']
llvm_fps = d['results']['llvm']['mean_fps']
print(f'x264 advantage: {(llvm_fps-msvc_fps)/msvc_fps*100:.1f}%')
