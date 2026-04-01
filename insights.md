# Insights: MSVC vs Clang/LLVM on Windows ARM64

Collected from benchmark runs on two ARM64 Windows machines:

| Machine | SoC | Cores | OS |
|---------|-----|-------|-----|
| **GLEB-DEVKIT** (Volterra) | Qualcomm Snapdragon 8cx Gen 3 | 8 | Windows 11 (10.0.27975) |
| **GLEB-SURFACE-15** | Qualcomm Snapdragon X Elite (X1E80100) | 12 | Windows 11 (10.0.26593) |

**Compilers tested**: MSVC 19.44.35224 (v14.44) vs LLVM/Clang 22.1.1 (clang-cl)

---

## 1. Summary of Results

### Volterra — Snapdragon 8cx Gen 3

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 1.108s mean | 0.815s mean | **+26.4% faster** |
| **NumPy sqrt** | 4.968ms mean | 4.255ms mean | **+14.4% faster** |
| **NumPy sort** | 82.74ms mean | 45.24ms mean | **+45.3% faster** |
| **x264** (H.264 encode) | 3.09 fps | 4.46 fps | **+44.3% faster** |
| **CPython** (geo-mean) | 76.30ms | 59.37ms | **+22.2% faster** |

### Surface Laptop 15 — Snapdragon X Elite (X1E80100)

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 0.576s mean | 0.402s mean | **+30.3% faster** |
| **NumPy sqrt** | 2.667ms mean | 2.146ms mean | **+19.5% faster** |
| **NumPy sort** | 63.96ms mean | 25.79ms mean | **+59.7% faster (2.5×)** |
| **x264** (H.264 encode) | 7.70 fps | 9.84 fps | **+27.8% faster** |
| **CPython** (geo-mean) | 48.78ms | 32.11ms | **+34.2% faster** |

**Overall finding**: LLVM/Clang produces **consistently and significantly faster code** than MSVC for ARM64 Windows across both platforms, with advantages ranging from **14% to 60%** depending on the workload. The gap is present on both an older (8cx Gen 3) and a current-generation (X Plus) Snapdragon SoC.

---

## 2. Detailed Benchmark Data

### 2.1 LAME MP3 Encoder (SVN r6531)
- **Build system**: MSBuild (VS2019 solution), custom override props
- **Workload**: Encode WAV → MP3 with "extreme" preset, 20 runs

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 1.108s (min 1.097, max 1.139) | 0.815s (min 0.805, max 0.830) | +26.4% |
| Surface 15 (X Elite) | 0.576s (min 0.571, max 0.586) | 0.402s (min 0.394, max 0.406) | +30.3% |

- **Key insight**: LAME is a float-heavy, loop-intensive encoder. LLVM's ARM64 backend generates better instruction scheduling and vectorization for the core DCT/psychoacoustic model loops. LLVM also shows tighter variance (more consistent performance).

### 2.2 NumPy (v2.4.1) — sqrt & sort
- **Build system**: Meson with native cross-files
- **Workload**: `sqrt` and `sort` on 1M-element float64 arrays, 50 runs each
- **Note**: Earlier benchmarks used `count_nonzero`, which was memory-bandwidth-bound on the faster X Plus chip and showed near-zero compiler difference. Switched to compute-intensive operations that exercise compiler codegen.

**sqrt (1M float64)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 4.968ms (min 4.685) | 4.255ms (min 4.060) | +14.4% |
| Surface 15 (X Elite) | 2.667ms (min 2.588) | 2.146ms (min 2.043) | +19.5% |

**sort (1M float64, quicksort)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 82.74ms (min 80.47) | 45.24ms (min 42.82) | +45.3% |
| Surface 15 (X Elite) | 63.96ms (min 63.72) | 25.79ms (min 25.54) | +59.7% (2.5×) |

- **Key insight**: `sort` is the standout result — LLVM generates dramatically better quicksort code on ARM64, with a 2.5× advantage on X Plus. This benchmark is branch-heavy and cache-intensive, exercising the compiler's ability to generate efficient comparison, swap, and branch sequences. `sqrt` tests NEON vectorization of a simpler element-wise operation. Both are compiler-sensitive (not memory-bandwidth-bound).

### 2.3 x264 H.264 Encoder (stable branch)
- **Build system**: Direct cl/clang-cl compilation (pure C, no hand-written ASM)
- **Workload**: Encode 300 frames of 720p YUV420 → H.264, medium preset, 3 runs

| Machine | MSVC mean fps | LLVM mean fps | LLVM Advantage |
|---------|---------------|---------------|----------------|
| Volterra (8cx Gen 3) | 3.09 (2.85–3.29) | 4.46 (4.42–4.48) | +44.3% |
| Surface 15 (X Elite) | 7.70 (7.70–7.71) | 9.84 (9.67–9.95) | +27.8% |

- **Key insight**: x264 is extremely compute-intensive with tight inner loops for motion estimation, DCT, quantization, and entropy coding. LLVM produces better ARM64 code for these patterns with all hand-written ASM disabled, isolating pure compiler codegen quality. LLVM also shows dramatically tighter variance on both machines.

### 2.4 CPython pyperformance (v3.14.2, 15 CPU-bound benchmarks)
- **Build system**: MSBuild (PCBuild)
- **Workload**: 15 CPU-bound pyperformance benchmarks with --rigorous (40 runs each)

**Volterra (Snapdragon 8cx Gen 3)** — LLVM geo-mean: 59.37ms, MSVC geo-mean: 76.30ms (**+22.2%**):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 125.76 | 95.35 | 24.2% |
| crypto_pyaes | 174.23 | 130.12 | 25.3% |
| deltablue | 7.55 | 5.37 | 28.8% |
| fannkuch | 778.76 | 663.33 | 14.8% |
| float | 145.93 | 112.64 | 22.8% |
| go | 234.56 | 169.24 | 27.9% |
| hexiom | 13.35 | 9.99 | 25.2% |
| nbody | 207.16 | 165.36 | 20.2% |
| pickle_pure_python | 0.79 | 0.56 | 29.0% |
| pidigits | 289.24 | 327.90 | −13.4% (MSVC faster) |
| pyflate | 936.25 | 722.16 | 22.9% |
| raytrace | 576.54 | 437.28 | 24.2% |
| richards | 96.37 | 68.82 | 28.6% |
| spectral_norm | 220.11 | 181.83 | 17.4% |
| unpickle_pure_python | 0.54 | 0.39 | 26.8% |

**Surface Laptop 15 (Snapdragon X Elite)** — LLVM geo-mean: 32.11ms, MSVC geo-mean: 48.78ms (**+34.2%**):

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

- **Key insight**: LLVM is faster on 14 out of 15 benchmarks on both machines. The sole exception is **pidigits** (bignum arithmetic via GMP/libmpz) where MSVC is faster — likely due to the GMP library itself or how the compilers handle the Python-to-C boundary for GMP calls. The LLVM advantage is larger on the X Elite (25–43%) than on the 8cx Gen 3 (15–29%), suggesting LLVM better exploits the newer microarchitecture.

---

## 3. Cross-Platform Comparison

The Surface Laptop 15 (X Elite, 12 cores) is roughly **1.8–2× faster** than the Volterra (8cx Gen 3, 8 cores) in absolute terms across all benchmarks. Interestingly, the **LLVM advantage tends to be larger on the newer chip**:

| Benchmark | 8cx Gen 3 LLVM adv. | X Elite LLVM adv. |
|-----------|---------------------|------------------|
| LAME MP3 | +26.4% | +30.3% |
| NumPy sqrt | +14.4% | +19.5% |
| NumPy sort | +45.3% | +59.7% |
| x264 | +44.3% | +27.8% |
| CPython (geo) | +22.2% | +34.2% |

The x264 result bucks the trend (larger gap on the older chip) — this may be because x264's inner loops hit different bottlenecks (memory latency vs ALU throughput) on the two microarchitectures.

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
3. **MSVC intrinsics gaps**: Newer ARM64 system register constants (`ARM64_CNTVCT_EL0`, `ARM64_CNTFRQ_EL0`) are missing in MSVC 14.44. Blender Cycles required manual fallback definitions.
4. **SxS manifest embedding**: clang-cl/lld-link does not automatically embed SxS manifests into executables. Applications depending on private assemblies (like Blender) require a manual `mt.exe` step.

### 5.3 Project-Specific Findings
- **LAME**: The VS2019 solution had no ARM64 platform. Required XML patching to clone x64 configurations, add ARM64 `CustomBuild` conditions for `configMS.h → config.h` copy, and exclude x86-specific SSE files (`xmm_quantize_sub.c`).
- **NumPy**: Meson build with native cross-files (`.ini`) works for both toolchains. No BLAS/LAPACK (built with internal fallback). Original `count_nonzero` benchmark was memory-bandwidth-bound on the X Elite, showing near-zero compiler difference. Switched to `sqrt` and `sort` which are compute-bound and reveal genuine compiler codegen differences.
- **CPython**: Both toolchains produce working Python interpreters. The LLVM-built CPython runs pyperformance benchmarks 22–34% faster depending on the machine.
- **x264**: Built from source with handcrafted `config.h` (no autotools/MSYS2). x264's unity build pattern (`.c` files `#include`-ing other `.c` files) requires careful source file management. All hand-written ASM disabled to isolate compiler codegen quality.

---

## 6. Architecture-Specific Observations

### 6.1 ARM64 Code Generation Quality
- LLVM's ARM64 (AArch64) backend has benefited from years of optimization for server and mobile ARM targets (Linux, Android, macOS/Apple Silicon). This maturity shows in consistently better instruction selection and scheduling.
- MSVC's ARM64 backend is newer and produces correct but less optimized code, particularly for:
  - Tight computational loops (seen in all benchmarks)
  - Auto-vectorization (NumPy sqrt's 15–20% gap suggests MSVC generates less efficient NEON code)
  - Sorting/branching (NumPy sort's 2.5× gap is the most dramatic evidence of codegen quality difference)
  - Code scheduling and register allocation (x264's tight LLVM variance suggests better pipeline utilization)

### 6.2 Microarchitecture Sensitivity
- The LLVM advantage is generally **larger on the newer X Elite** chip (except x264), suggesting LLVM better exploits features of the newer Qualcomm Oryon cores.
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
| **4. Runtime Performance** | 14–60% advantage for LLVM across all tested workloads on both platforms |
| **5. Platform Features** | MSVC offers ARM64EC (not tested); Clang offers cross-platform consistency |
| **6. Developer Experience** | MSVC setup has gaps (vswhere, vcvarsall issues); clang-cl flag syntax is confusing but functional |
| **7. Use Cases** | Audio/video encoding, numerical computing, language runtimes all favor LLVM |
| **8. Limitations** | MSVC is Windows-only; LLVM is open-source; some projects (Blender) only support specific toolchains |
| **9. Methodology** | 4 real-world projects, 2 ARM64 machines, CPU-pinned, high-priority, multiple runs, structured JSON output |
| **10. Future Directions** | SVE/SVE2 not yet exploited by either compiler on Windows; MSVC ARM64 backend likely to improve |
