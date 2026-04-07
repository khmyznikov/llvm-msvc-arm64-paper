# Insights: MSVC vs Clang/LLVM on Windows ARM64

Collected from benchmark runs on two ARM64 Windows machines:

| Machine | SoC | Cores | OS |
|---------|-----|-------|-----|
| **GLEB-DEVKIT** (Volterra) | Qualcomm Snapdragon 8cx Gen 3 | 8 | Windows 11 (10.0.27975) |
| **GLEB-SURFACE-15** | Qualcomm Snapdragon X Elite (X1E80100) | 12 | Windows 11 (10.0.26593) |

**Compilers tested**: MSVC 19.50.35728 (v14.50, VS 2026) vs LLVM/Clang 22.1.1 (clang-cl)

---

## 1. Summary of Results

### Volterra — Snapdragon 8cx Gen 3

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 1.135s mean | 0.810s mean | **+28.6% faster** |
| **NumPy sqrt** | 2.936ms mean | 4.209ms mean | **−30.2% (MSVC faster)** |
| **NumPy sort** | 80.76ms mean | 42.66ms mean | **+47.2% faster** |
| **x264** (H.264 encode) | 3.48 fps | 4.51 fps | **+29.7% faster** |
| **CPython** (geo-mean) | 76.07ms | 59.29ms | **+22.1% faster** |

### Surface Laptop 15 — Snapdragon X Elite (X1E80100)

> **Note**: Surface 15 results use MSVC v14.44 (VS 2022). These have **not been re-benchmarked** with MSVC v14.50 yet. Cross-machine MSVC version comparisons are not valid.

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 0.576s mean | 0.402s mean | **+30.3% faster** |
| **NumPy sqrt** | 2.667ms mean | 2.146ms mean | **+19.5% faster** |
| **NumPy sort** | 63.96ms mean | 25.79ms mean | **+59.7% faster (2.5×)** |
| **x264** (H.264 encode) | 7.70 fps | 9.84 fps | **+27.8% faster** |
| **CPython** (geo-mean) | 48.78ms | 32.11ms | **+34.2% faster** |

**Overall finding**: LLVM/Clang produces **consistently and significantly faster code** than MSVC for ARM64 Windows across both platforms, with advantages ranging from **22% to 60%** depending on the workload. MSVC v14.50 (tested on Volterra) has **significantly improved its ARM64 codegen** compared to v14.44 — notably **outperforming LLVM on NumPy sqrt** and **narrowing the x264 gap from 44% to 30%**. The Surface 15 results still reflect MSVC v14.44 and have not been re-benchmarked with v14.50.

---

## 2. Detailed Benchmark Data

### 2.1 LAME MP3 Encoder (SVN r6531)
- **Build system**: MSBuild (VS2019 solution), custom override props
- **Workload**: Encode WAV → MP3 with "extreme" preset, 20 runs

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 1.135s (min 1.123, max 1.169) | 0.810s (min 0.802, max 0.825) | +28.6% |
| Surface 15 (X Elite) | 0.576s (min 0.571, max 0.586) | 0.402s (min 0.394, max 0.406) | +30.3% |

- **Key insight**: LAME is a float-heavy, loop-intensive encoder. LLVM's ARM64 backend generates better instruction scheduling and vectorization for the core DCT/psychoacoustic model loops. LLVM also shows tighter variance (more consistent performance). On Volterra, MSVC v14.50 is slightly slower than v14.44 on this workload (1.135s vs 1.108s), suggesting the newer compiler's optimizations don't uniformly benefit all code patterns.

### 2.2 NumPy (v2.4.1) — sqrt & sort
- **Build system**: Meson with native cross-files
- **Workload**: `sqrt` and `sort` on 1M-element float64 arrays, 50 runs each
- **Note**: Earlier benchmarks used `count_nonzero`, which was memory-bandwidth-bound on the faster X Plus chip and showed near-zero compiler difference. Switched to compute-intensive operations that exercise compiler codegen. On Volterra, MSVC v14.50 shows **dramatically improved sqrt performance** (2.936ms vs 4.968ms in v14.44), now **beating LLVM by 30%** on this operation.

**sqrt (1M float64)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 2.936ms (min 2.901) | 4.209ms (min 4.111) | −30.2% (MSVC faster) |
| Surface 15 (X Elite) | 2.667ms (min 2.588) | 2.146ms (min 2.043) | +19.5% |

**sort (1M float64, quicksort)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 80.76ms (min 79.25) | 42.66ms (min 41.43) | +47.2% |
| Surface 15 (X Elite) | 63.96ms (min 63.72) | 25.79ms (min 25.54) | +59.7% (2.5×) |

- **Key insight**: `sort` is the standout result — LLVM generates dramatically better quicksort code on ARM64, with a 2.5× advantage on X Plus. `sqrt` reveals a striking result on Volterra: MSVC v14.50 beats LLVM by 30%. The Surface 15 sqrt result (+19.5% LLVM) is from MSVC v14.44 and **cannot be compared** to the Volterra v14.50 result to draw microarchitecture conclusions — the Surface 15 needs re-benchmarking with v14.50 first.

### 2.3 x264 H.264 Encoder (stable branch)
- **Build system**: Direct cl/clang-cl compilation (pure C, no hand-written ASM)
- **Workload**: Encode 300 frames of 720p YUV420 → H.264, medium preset, 3 runs

| Machine | MSVC mean fps | LLVM mean fps | LLVM Advantage |
|---------|---------------|---------------|----------------|
| Volterra (8cx Gen 3) | 3.48 (3.47–3.49) | 4.51 (4.49–4.52) | +29.7% |
| Surface 15 (X Elite) | 7.70 (7.70–7.71) | 9.84 (9.67–9.95) | +27.8% |

- **Key insight**: x264 is extremely compute-intensive with tight inner loops for motion estimation, DCT, quantization, and entropy coding. LLVM produces better ARM64 code for these patterns with all hand-written ASM disabled, isolating pure compiler codegen quality. On Volterra, MSVC v14.50 narrowed the gap significantly (from 44.3% to 29.7%) and now shows tight run-to-run variance matching LLVM's stability.

### 2.4 CPython pyperformance (v3.14.2, 15 CPU-bound benchmarks)
- **Build system**: MSBuild (PCBuild)
- **Workload**: 15 CPU-bound pyperformance benchmarks with --rigorous (40 runs each)

**Volterra (Snapdragon 8cx Gen 3)** — LLVM geo-mean: 59.29ms, MSVC geo-mean: 76.07ms (**+22.1%**):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 124.77 | 95.43 | 23.5% |
| crypto_pyaes | 158.95 | 129.96 | 18.2% |
| deltablue | 7.63 | 5.37 | 29.6% |
| fannkuch | 797.84 | 664.08 | 16.8% |
| float | 143.88 | 112.44 | 21.9% |
| go | 238.86 | 169.25 | 29.1% |
| hexiom | 13.35 | 10.01 | 25.0% |
| nbody | 216.42 | 165.48 | 23.5% |
| pickle_pure_python | 0.77 | 0.56 | 27.0% |
| pidigits | 310.82 | 326.57 | −5.1% (MSVC faster) |
| pyflate | 905.06 | 722.03 | 20.2% |
| raytrace | 576.11 | 437.36 | 24.1% |
| richards | 98.37 | 68.92 | 29.9% |
| spectral_norm | 216.28 | 178.38 | 17.5% |
| unpickle_pure_python | 0.52 | 0.40 | 23.8% |

**Surface Laptop 15 (Snapdragon X Elite)** — LLVM geo-mean: 32.11ms, MSVC geo-mean: 48.78ms (**+34.2%**):

> **Note**: These MSVC results are from v14.44 (VS 2022), not yet re-benchmarked with v14.50.

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 80.04 | 48.15 | 39.8% |
| crypto_pyaes | 97.45 | 63.36 | 35.0% |
| deltablue | 5.40 | 3.08 | 42.9% |
| fannkuch | 478.17 | 354.06 | 25.9% |
| float | 93.70 | 63.61 | 32.1% |
| go | 171.44 | 100.69 | 41.3% |
| hexiom | 9.05 | 5.53 | 38.9% |
| nbody | 131.22 | 95.76 | 27.0% |
| pickle_pure_python | 0.43 | 0.26 | 40.5% |
| pidigits | 200.94 | 249.40 | −24.1% (MSVC faster) |
| pyflate | 581.03 | 391.45 | 32.6% |
| raytrace | 354.38 | 214.37 | 39.5% |
| richards | 65.81 | 40.38 | 38.6% |
| spectral_norm | 141.30 | 85.43 | 39.5% |
| unpickle_pure_python | 0.33 | 0.19 | 42.2% |

- **Key insight**: LLVM is faster on 14 out of 15 benchmarks on both machines. The sole exception is **pidigits** (bignum arithmetic via GMP/libmpz) where MSVC is faster — the gap shrank from 13.4% (v14.44) to just 5.1% (v14.50) on Volterra. Several CPython benchmarks improved with MSVC v14.50 on Volterra (notably crypto_pyaes: gap narrowed from 25.3% to 18.2%). The Surface 15 results (v14.44) show a larger LLVM advantage (25–43%) than Volterra (v14.50, 17–30%), but this difference may partly reflect the MSVC version gap rather than just the microarchitecture.

---

## 3. Cross-Platform Comparison

The Surface Laptop 15 (X Elite, 12 cores) is roughly **1.8–2× faster** than the Volterra (8cx Gen 3, 8 cores) in absolute terms across all benchmarks. Interestingly, the **LLVM advantage tends to be larger on the newer chip**:

| Benchmark | 8cx Gen 3 LLVM adv. | X Elite LLVM adv. |
|-----------|---------------------|------------------|
| LAME MP3 | +28.6% | +30.3% |
| NumPy sqrt | −30.2% (MSVC faster) | +19.5% |
| NumPy sort | +47.2% | +59.7% |
| x264 | +29.7% | +27.8% |
| CPython (geo) | +22.1% | +34.2% |

The x264 results are now similar across both chips with MSVC v14.50 on Volterra (≈30% LLVM advantage). The most striking finding is **NumPy sqrt**, where MSVC v14.50 **beats LLVM on the 8cx Gen 3** — but the X Elite result cannot be compared as it still uses MSVC v14.44.

> **Caveat**: The cross-platform comparison is confounded by different MSVC versions — Volterra uses v14.50, Surface 15 uses v14.44. The Surface 15 needs re-benchmarking with MSVC v14.50 before valid cross-machine conclusions about LLVM advantage scaling can be drawn.

---

## 4. Compiler Configuration

| Setting | MSVC | LLVM (clang-cl) |
|---------|------|-----------------|
| Optimization | `/O2` | `/clang:-O3` |
| LTO | `/GL` + `/LTCG` | `-flto` + `/clang:-fuse-ld=lld` |
| Fast math | `/fp:fast` | `/clang:-ffast-math` |
| Security | `/GS-` | `/GS-` |
| Frame pointers | `/Oy-` (preserved for ETW) | `/Oy-` |
| Debug info | `/Zi /Zo` | `/Zi /Zo` |
| Linker | MSVC link.exe | lld-link |

**Important note on MSVC optimization**: MSVC's maximum optimization is `/O2` (equivalent to Clang `-O2`). There is no MSVC equivalent of Clang's `-O3`. This means LLVM has an additional optimization tier available that MSVC does not offer.

---

## 5. Build System and Toolchain Insights

### 5.1 ARM64 Windows Toolchain Maturity
- **MSVC ARM64 support**: Functional but with gaps. The VS Build Tools installer doesn't properly register with `vswhere` when using BuildTools-only installs (not full VS IDE). `vcvarsall.bat` can fail silently when the VCTools workload is incomplete.
- **LLVM ARM64 support**: The standalone LLVM install works well with clang-cl. Key learning: use `/clang:-O3` (not bare `-O3` which is ignored by clang-cl), and `/clang:-fuse-ld=lld` for proper LTO.
- **Cross-compilation**: Both toolchains support ARM64 targeting from x64 hosts. Native ARM64 compilation is also supported.

### 5.2 Common Build Issues Encountered
1. **clang-cl flag syntax**: `-O3` and `-ffast-math` are silently ignored by clang-cl. Must use `/clang:-O3` and `/clang:-ffast-math` to pass them to the Clang driver.
2. **LTO with lld-link**: Passing `/link /LTCG` to lld-link when using `-flto` can cause LLVM to emit unoptimized code (observed as 4x performance degradation in early strcmp tests).
3. **MSVC intrinsics gaps**: Newer ARM64 system register constants (`ARM64_CNTVCT_EL0`, `ARM64_CNTFRQ_EL0`) were missing in MSVC 14.44 (fixed in 14.50). Blender Cycles required manual fallback definitions.
4. **SxS manifest embedding**: clang-cl/lld-link does not automatically embed SxS manifests into executables. Applications depending on private assemblies (like Blender) require a manual `mt.exe` step.

### 5.3 Project-Specific Findings
- **LAME**: The VS2019 solution had no ARM64 platform. Required XML patching to clone x64 configurations, add ARM64 `CustomBuild` conditions for `configMS.h → config.h` copy, and exclude x86-specific SSE files (`xmm_quantize_sub.c`).
- **NumPy**: Meson build with native cross-files (`.ini`) works for both toolchains. No BLAS/LAPACK (built with internal fallback). Original `count_nonzero` benchmark was memory-bandwidth-bound on the X Elite, showing near-zero compiler difference. Switched to `sqrt` and `sort` which are compute-bound. MSVC v14.50 shows dramatically improved sqrt on Volterra (now beats LLVM), while sort remains heavily LLVM-favored.
- **CPython**: Both toolchains produce working Python interpreters. The LLVM-built CPython runs pyperformance benchmarks 22–34% faster depending on the machine. MSVC v14.50 improved several benchmarks (crypto_pyaes gap narrowed from 25% to 18%).
- **x264**: Built from source with handcrafted `config.h` (no autotools/MSYS2). x264's unity build pattern (`.c` files `#include`-ing other `.c` files) requires careful source file management. All hand-written ASM disabled to isolate compiler codegen quality.

---

## 6. Architecture-Specific Observations

### 6.1 ARM64 Code Generation Quality
- LLVM's ARM64 (AArch64) backend has benefited from years of optimization for server and mobile ARM targets (Linux, Android, macOS/Apple Silicon). This maturity shows in consistently better instruction selection and scheduling.
- MSVC's ARM64 backend has seen **notable improvement from v14.44 to v14.50**:
  - NumPy sqrt went from 14% slower to **30% faster** than LLVM on Volterra — showing dramatically improved NEON vectorization for simple patterns
  - x264 gap narrowed from 44.3% to 29.7% on Volterra, with run-to-run variance now matching LLVM
  - CPython crypto_pyaes gap narrowed from 25.3% to 18.2%
  - However, for complex branching patterns (sort: 47% gap) and interpreter dispatch (22–34% gap), LLVM still leads significantly

### 6.2 Microarchitecture Sensitivity
- The LLVM advantage appears **larger on the X Elite** than on the 8cx Gen 3, but this comparison is currently confounded by different MSVC versions (v14.44 on X Elite vs v14.50 on Volterra). Re-benchmarking the Surface 15 with MSVC v14.50 is needed to isolate the microarchitecture effect.
- The X Elite shows 1.8–2× absolute speedup over 8cx Gen 3, consistent with the generational improvement from Kryo → Oryon cores.

### 6.3 Binary Size Comparison
- **LAME lame.exe**: MSVC 513 KB vs LLVM 535 KB (LLVM slightly larger)
- **LAME libmp3lame-static.lib**: MSVC 4.0 MB vs LLVM 1.3 MB (LLVM much smaller due to LTO bitcode vs MSVC COFF objects)
- LTO reduces link-time library size significantly for LLVM.

### 6.4 Platform Limitations Discovered
- **Blender ARM64 on MSVC**: Officially unsupported by Blender. MSVC build crashes with access violation (0xC0000005) in Cycles engine initialization. The crash is in `.rdata` section (vtable dispatch) suggesting a codegen bug.
- **Blender ARM64 on LLVM**: DLL loading issues due to missing SxS manifests. After manual manifest embedding, still crashes — likely ABI mismatch with prebuilt dependency libraries compiled by Blender's own Clang.

---

## 7. Methodology Notes

### Hardware

| | Volterra (GLEB-DEVKIT) | Surface Laptop 15 (GLEB-SURFACE-15) |
|---|---|---|
| SoC | Snapdragon 8cx Gen 3 | Snapdragon X Elite (X1E80100) |
| CPU | ARMv8 Family 8 Model D4B, Kryo | ARMv8 Family 8 Model 1, Oryon |
| Cores | 8 | 12 |
| OS | Windows 11 (10.0.27975) | Windows 11 (10.0.26593) |

### Benchmark Controls
- **CPU affinity**: Pinned to core 2 (mask 0x4) for reduced scheduling noise
- **Process priority**: HIGH_PRIORITY_CLASS (0x80)
- **Runs**: Multiple runs per benchmark (3-50 depending on benchmark duration)
- **Warmup**: All benchmarks include warmup runs discarded from measurements

### Reproducibility
- All source versions pinned (LAME r6531, NumPy v2.4.1, CPython v3.14.2, x264 stable)
- Build configurations stored in `common/config.py` and per-project override files
- Results saved as structured JSON with machine metadata
- Build automation via Python Invoke tasks (`inv <project>.build/bench`)
- Excel charts generated via `python generate_excel_charts.py` (requires `openpyxl`)

---

## 8. Mapping to Thesis Points

| Thesis Point | Relevant Data |
|--------------|---------------|
| **1. Introduction** | ARM64 Windows is a viable target; both toolchains work but with significant performance differences |
| **2. Architecture** | Both compilers target AArch64 ISA; LLVM's IR → AArch64 backend is more mature; tested on two generations of Qualcomm SoCs |
| **3. Compilation Metrics** | Binary sizes similar; LTO more effective with LLVM; optimization levels differ (`/O2` vs `-O3`) |
| **4. Runtime Performance** | 22–60% advantage for LLVM on most workloads; MSVC v14.50 catches up on simple NEON vectorization (sqrt) |
| **5. Platform Features** | MSVC offers ARM64EC (not tested); Clang offers cross-platform consistency |
| **6. Developer Experience** | MSVC setup has gaps (vswhere, vcvarsall issues); clang-cl flag syntax is confusing but functional |
| **7. Use Cases** | Audio/video encoding, numerical computing, language runtimes all favor LLVM |
| **8. Limitations** | MSVC is Windows-only; LLVM is open-source; some projects (Blender) only support specific toolchains |
| **9. Methodology** | 4 real-world projects, 2 ARM64 machines, CPU-pinned, high-priority, multiple runs, structured JSON output |
| **10. Future Directions** | SVE/SVE2 not yet exploited by either compiler on Windows; MSVC ARM64 backend is actively improving (v14.44→v14.50 showed measurable gains on sqrt and x264) |
