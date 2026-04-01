"""Investigate NumPy benchmark timing distributions across both machines."""
import json, statistics
from pathlib import Path

RESULTS = Path("results")

def analyze(machine_id, label):
    print(f"\n{'='*60}")
    print(f"  {label} ({machine_id})")
    print(f"{'='*60}")
    for tc in ("llvm", "msvc"):
        path = RESULTS / machine_id / "numpy" / f"numpy_{tc}_arm64.json"
        with open(path) as f:
            d = json.load(f)
        times = d["times_sec"]
        times_us = [t * 1e6 for t in times]  # microseconds
        sorted_us = sorted(times_us)

        mean = statistics.mean(times_us)
        median = statistics.median(times_us)
        stdev = statistics.stdev(times_us)
        p5 = sorted_us[int(len(sorted_us) * 0.05)]
        p25 = sorted_us[int(len(sorted_us) * 0.25)]
        p75 = sorted_us[int(len(sorted_us) * 0.75)]
        p95 = sorted_us[int(len(sorted_us) * 0.95)]
        mn = min(times_us)
        mx = max(times_us)

        print(f"\n  {tc.upper():5s}  (µs):")
        print(f"    min={mn:.1f}  p5={p5:.1f}  p25={p25:.1f}  median={median:.1f}  p75={p75:.1f}  p95={p95:.1f}  max={mx:.1f}")
        print(f"    mean={mean:.1f}  stdev={stdev:.1f}  CV={stdev/mean*100:.1f}%")

        # Show histogram buckets
        bucket_size = 20  # µs
        lo = int(mn // bucket_size) * bucket_size
        hi = int(mx // bucket_size + 1) * bucket_size
        print(f"    Distribution (bucket={bucket_size}µs):")
        for b_start in range(lo, hi + 1, bucket_size):
            b_end = b_start + bucket_size
            count = sum(1 for t in times_us if b_start <= t < b_end)
            if count > 0:
                bar = "#" * count
                print(f"      {b_start:4d}-{b_end:4d}: {bar} ({count})")

    # Compare
    llvm_d = json.load(open(RESULTS / machine_id / "numpy" / "numpy_llvm_arm64.json"))
    msvc_d = json.load(open(RESULTS / machine_id / "numpy" / "numpy_msvc_arm64.json"))
    llvm_med = statistics.median(llvm_d["times_sec"])
    msvc_med = statistics.median(msvc_d["times_sec"])
    llvm_min = min(llvm_d["times_sec"])
    msvc_min = min(msvc_d["times_sec"])
    llvm_mean = statistics.mean(llvm_d["times_sec"])
    msvc_mean = statistics.mean(msvc_d["times_sec"])

    print(f"\n  Comparison:")
    print(f"    By mean:   LLVM {llvm_mean*1e6:.1f}µs vs MSVC {msvc_mean*1e6:.1f}µs  → LLVM {(msvc_mean-llvm_mean)/msvc_mean*100:+.1f}%")
    print(f"    By median: LLVM {llvm_med*1e6:.1f}µs vs MSVC {msvc_med*1e6:.1f}µs  → LLVM {(msvc_med-llvm_med)/msvc_med*100:+.1f}%")
    print(f"    By min:    LLVM {llvm_min*1e6:.1f}µs vs MSVC {msvc_min*1e6:.1f}µs  → LLVM {(msvc_min-llvm_min)/msvc_min*100:+.1f}%")


analyze("gleb-devkit-arm64", "Volterra (8cx Gen 3)")
analyze("gleb-surface-15-arm64", "Surface Laptop 15 (X Plus)")
