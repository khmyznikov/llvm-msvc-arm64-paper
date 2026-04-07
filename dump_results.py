import json, statistics, math
from pathlib import Path

machines = {
    "gleb-devkit-arm64": "Volterra (Snapdragon 8cx Gen 3)",
    "gleb-surface-15-arm64": "Surface Laptop 15 (Snapdragon X Plus)",
}

for mid, label in machines.items():
    print(f"\n=== {label} ({mid}) ===")

    # LAME
    for tc in ("llvm", "msvc"):
        d = json.load(open(f"results/{mid}/lame/lame_{tc}_arm64.json"))
        print(f"  LAME {tc}: mean={d['mean_sec']:.4f}s min={d['min_sec']:.4f}s max={d['max_sec']:.4f}s")

    # x264
    d = json.load(open(f"results/{mid}/x264/x264_results_arm64.json"))
    for tc in ("msvc", "llvm"):
        r = d["results"][tc]
        print(f"  x264 {tc}: mean_fps={r['mean_fps']:.2f} min={r['min_fps']:.2f} max={r['max_fps']:.2f}")

    # NumPy
    for tc in ("llvm", "msvc"):
        nd = json.load(open(f"results/{mid}/numpy/numpy_{tc}_arm64.json"))
        if "operations" in nd:
            print(f"  NumPy {tc} (suite):")
            for op, od in nd["operations"].items():
                print(f"    {op}: mean={od['mean_sec']*1e3:.3f}ms min={od['min_sec']*1e3:.3f}ms")
        else:
            m = statistics.mean(nd["times_sec"])
            print(f"  NumPy {tc} (legacy): mean={m*1e6:.1f}us")

    # CPython
    for tc in ("llvm", "msvc"):
        cd = json.load(open(f"results/{mid}/cpython/pyperformance_{tc}_arm64.json"))
        bm = {}
        for b in cd["benchmarks"]:
            name = b["metadata"]["name"]
            vals = []
            for run in b["runs"]:
                if "values" in run:
                    vals.extend(run["values"])
            if vals:
                bm[name] = statistics.mean(vals)
        geo = math.exp(sum(math.log(v) for v in bm.values()) / len(bm))
        print(f"  CPython {tc}: geo_mean={geo*1e3:.2f}ms")
        for n, v in sorted(bm.items()):
            print(f"    {n}: {v*1e3:.2f}ms")

    # Machine info
    d = json.load(open(f"results/{mid}/lame/lame_llvm_arm64.json"))
    mi = d["machine"]
    print(f"  Machine: {mi}")
