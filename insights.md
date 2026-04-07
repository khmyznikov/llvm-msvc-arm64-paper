# Insights: MSVC vs Clang/LLVM on Windows ARM64

Collected from benchmark runs on **GLEB-DEVKIT** (Qualcomm Snapdragon X Elite, ARM64, Windows 11, 8 cores).

**Compilers tested**: MSVC 19.50.35728 (v14.50, VS 2026) vs LLVM/Clang 22.1.1 (clang-cl)

---

## 1. Summary of Results

| Benchmark | MSVC | LLVM | LLVM Advantage | Category |
|-----------|------|------|----------------|----------|
| **LAME MP3** (encode) | 1.135s mean | 0.810s mean | **+28.6% faster** | Audio encoding |
| **NumPy** (sqrt, 1M) | 2.94ms mean | 4.21ms mean | **−30.2% (MSVC faster)** | Numerical (math ufunc) |
| **NumPy** (sort, 1M) | 80.76ms mean | 42.66ms mean | **+47.2% faster** | Numerical (sort) |
| **x264** (H.264 encode) | 3.48 fps | 4.51 fps | **+29.6% faster** | Video encoding |
| **CPython** (pyperformance) | varies | varies | **~15.9–30.1% faster** | Interpreter (mixed workload) |

**Overall finding**: LLVM/Clang produces **consistently faster code** than MSVC for ARM64 Windows on compute-intensive workloads, with advantages of 28–47% for loop-heavy C code and 16–30% for the CPython interpreter. However, MSVC v14.50 has **significantly narrowed the gap** compared to v14.44, and **outperforms LLVM on specific math ufuncs** (e.g. sqrt) — suggesting improved NEON codegen for simple vectorizable patterns.

---

## 2. Detailed Benchmark Data

### 2.1 LAME MP3 Encoder (SVN r6531)
- **Build system**: MSBuild (VS2019 solution), custom override props
- **Workload**: Encode WAV → MP3 with "extreme" preset, 20 runs
- **MSVC**: mean 1.135s, min 1.123s, max 1.169s (σ ≈ 0.011s)
- **LLVM**: mean 0.810s, min 0.802s, max 0.825s (σ ≈ 0.006s)
- **LLVM advantage**: 28.6% faster, also tighter variance (more consistent)
- **Key insight**: LAME is a float-heavy, loop-intensive encoder. LLVM's ARM64 backend generates better instruction scheduling and vectorization for the core DCT/psychoacoustic model loops. The gap narrowed from 35.9% (MSVC v14.44) to 28.6% (v14.50), indicating improved ARM64 codegen in the newer MSVC.

### 2.2 NumPy (v2.4.1) — sqrt and sort
- **Build system**: Meson with native cross-files
- **Workload**: sqrt and sort on 1M-element float64 array, 50 runs each
- **sqrt** (vectorizable math ufunc):
  - MSVC: mean 2.94ms, min 2.90ms, max 3.08ms
  - LLVM: mean 4.21ms, min 4.11ms, max 4.75ms
  - **MSVC 30.2% faster** — MSVC v14.50 generates better NEON code for this simple element-wise math loop
- **sort** (quicksort, branch-heavy + cache-intensive):
  - MSVC: mean 80.76ms, min 79.25ms, max 86.31ms
  - LLVM: mean 42.66ms, min 41.43ms, max 44.30ms
  - **LLVM 47.2% faster** — LLVM produces significantly better ARM64 code for branch-heavy sorting algorithms
- **Key insight**: The new MSVC v14.50 shows dramatically improved NEON vectorization for simple, regular patterns (sqrt). However, for complex branching patterns (sort), LLVM's advantage remains substantial. This suggests MSVC's auto-vectorizer has improved for straightforward cases but still lags on more complex control flow.

### 2.3 x264 H.264 Encoder (stable branch)
- **Build system**: Direct cl/clang-cl compilation (pure C, no hand-written ASM)
- **Workload**: Encode 300 frames of 720p YUV420 → H.264, medium preset, 3 runs
- **MSVC**: mean 3.48 fps (min 3.47, max 3.49)
- **LLVM**: mean 4.51 fps (min 4.49, max 4.52)
- **LLVM advantage**: 29.6% faster. Both toolchains now show tight variance.
- **Key insight**: x264 is an extremely compute-intensive codec with tight inner loops for motion estimation, DCT, quantization, and entropy coding. LLVM's -O3 still produces better ARM64 code for these patterns, but MSVC v14.50 has closed the gap significantly (from 44.3% to 29.6%) and now shows consistent run-to-run performance matching LLVM's stability.

### 2.4 CPython pyperformance (v3.14.2, 15 CPU-bound benchmarks)
- **Build system**: MSBuild (PCBuild)
- **Workload**: 15 CPU-bound pyperformance benchmarks with --rigorous (40 runs each)
- **Results per benchmark** (mean times, ms):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 124.8 | 95.3 | 23.6% |
| crypto_pyaes | 158.9 | 130.1 | 18.1% |
| deltablue | 7.63 | 5.37 | 29.6% |
| fannkuch | 797.8 | 663.3 | 16.9% |
| float | 143.9 | 112.6 | 21.7% |
| go | 238.9 | 169.2 | 29.2% |
| hexiom | 13.35 | 9.99 | 25.1% |
| nbody | 216.4 | 165.4 | 23.6% |
| pickle_pure_python | 0.771 | 0.563 | 27.0% |
| pidigits | 310.8 | 327.9 | -5.5% (MSVC faster) |
| pyflate | 905.1 | 722.2 | 20.2% |
| raytrace | 576.1 | 437.3 | 24.1% |
| richards | 98.4 | 68.8 | 30.1% |
| spectral_norm | 216.3 | 181.8 | 15.9% |
| unpickle_pure_python | 0.519 | 0.395 | 23.8% |

- **Key insight**: LLVM is faster on 14 out of 15 benchmarks by 15.9–30.1%. The sole exception is **pidigits** (bignum arithmetic via GMP/libmpz) where MSVC is 5.5% faster (down from 13% in v14.44). Several benchmarks improved with MSVC v14.50 (notably crypto_pyaes: gap narrowed from 25.3% to 18.1%), suggesting incremental ARM64 backend improvements.

---

## 3. Compiler Configuration

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

## 4. Build System and Toolchain Insights

### 4.1 ARM64 Windows Toolchain Maturity
- **MSVC ARM64 support**: Functional but with gaps. The VS Build Tools installer doesn't properly register with `vswhere` when using BuildTools-only installs (not full VS IDE). `vcvarsall.bat` can fail silently when the VCTools workload is incomplete.
- **LLVM ARM64 support**: The standalone LLVM install works well with clang-cl. Key learning: use `/clang:-O3` (not bare `-O3` which is ignored by clang-cl), and `/clang:-fuse-ld=lld` for proper LTO.
- **Cross-compilation**: Both toolchains support ARM64 targeting from x64 hosts. Native ARM64 compilation is also supported.

### 4.2 Common Build Issues Encountered
1. **clang-cl flag syntax**: `-O3` and `-ffast-math` are silently ignored by clang-cl. Must use `/clang:-O3` and `/clang:-ffast-math` to pass them to the Clang driver.
2. **LTO with lld-link**: Passing `/link /LTCG` to lld-link when using `-flto` can cause LLVM to emit unoptimized code (observed as 4x performance degradation in early strcmp tests).
3. **MSVC intrinsics gaps**: Newer ARM64 system register constants (`ARM64_CNTVCT_EL0`, `ARM64_CNTFRQ_EL0`) were missing in MSVC 14.44 (fixed in 14.50). Blender Cycles required manual fallback definitions.
4. **SxS manifest embedding**: clang-cl/lld-link does not automatically embed SxS manifests into executables. Applications depending on private assemblies (like Blender) require a manual `mt.exe` step.

### 4.3 Project-Specific Findings
- **LAME**: The VS2019 solution had no ARM64 platform. Required XML patching to clone x64 configurations, add ARM64 `CustomBuild` conditions for `configMS.h → config.h` copy, and exclude x86-specific SSE files (`xmm_quantize_sub.c`).
- **NumPy**: Meson build with native cross-files (`.ini`) works for both toolchains. No BLAS/LAPACK (built with internal fallback). Benchmarks (sqrt, sort) show a mixed picture: MSVC v14.50 wins on simple vectorizable ops, LLVM wins on complex branching.
- **CPython**: Both toolchains produce working Python interpreters. The LLVM-built CPython runs pyperformance benchmarks ~22% faster on average (geometric mean).
- **x264**: Built from source with handcrafted `config.h` (no autotools/MSYS2). x264's unity build pattern (`.c` files `#include`-ing other `.c` files) requires careful source file management. All hand-written ASM disabled to isolate compiler codegen quality.

---

## 5. Architecture-Specific Observations

### 5.1 ARM64 Code Generation Quality
- LLVM's ARM64 (AArch64) backend has benefited from years of optimization for server and mobile ARM targets (Linux, Android, macOS/Apple Silicon). This maturity shows in consistently better instruction selection and scheduling.
- MSVC's ARM64 backend has seen **notable improvement from v14.44 to v14.50**:
  - The LAME gap narrowed from 35.9% to 28.6%
  - The x264 gap narrowed from 44.3% to 29.6%, and run-to-run variance is now comparable
  - NumPy sqrt is now **faster on MSVC** — indicating improved NEON vectorization for regular patterns
  - However, for complex code patterns (branch-heavy loops, interpreter dispatch), LLVM still leads by 16–30%

### 5.2 Binary Size Comparison
- **LAME lame.exe**: MSVC 513 KB vs LLVM 535 KB (LLVM slightly larger)
- **LAME libmp3lame-static.lib**: MSVC 4.0 MB vs LLVM 1.3 MB (LLVM much smaller due to LTO bitcode vs MSVC COFF objects)
- LTO reduces link-time library size significantly for LLVM.

### 5.3 Platform Limitations Discovered
- **Blender ARM64 on MSVC**: Officially unsupported by Blender. MSVC build crashes with access violation (0xC0000005) in Cycles engine initialization. The crash is in `.rdata` section (vtable dispatch) suggesting a codegen bug.
- **Blender ARM64 on LLVM**: DLL loading issues due to missing SxS manifests. After manual manifest embedding, still crashes — likely ABI mismatch with prebuilt dependency libraries compiled by Blender's own Clang.

---

## 6. Methodology Notes

### Hardware
- **Machine**: GLEB-DEVKIT (Qualcomm Snapdragon X Elite, Windows 11 10.0.27975)
- **Architecture**: ARM64 (ARMv8, Family 8 Model D4B)
- **CPU**: 8 cores
- **Connection**: Remote Desktop (RDP)

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

---

## 7. Mapping to Thesis Points

| Thesis Point | Relevant Data |
|--------------|---------------|
| **1. Introduction** | ARM64 Windows is a viable target; both toolchains work but with significant performance differences |
| **2. Architecture** | Both compilers target AArch64 ISA; LLVM's IR → AArch64 backend is more mature |
| **3. Compilation Metrics** | Binary sizes similar; LTO more effective with LLVM; optimization levels differ (`/O2` vs `-O3`) |
| **4. Runtime Performance** | 15.9–47.2% advantage for LLVM on complex workloads; MSVC catches up on simple vectorizable patterns |
| **5. Platform Features** | MSVC offers ARM64EC (not tested); Clang offers cross-platform consistency |
| **6. Developer Experience** | MSVC setup has gaps (vswhere, vcvarsall issues); clang-cl flag syntax is confusing but functional |
| **7. Use Cases** | Audio/video encoding, numerical computing, language runtimes all favor LLVM |
| **8. Limitations** | MSVC is Windows-only; LLVM is open-source; some projects (Blender) only support specific toolchains |
| **9. Methodology** | 4 real-world projects, CPU-pinned, high-priority, multiple runs, structured JSON output |
| **10. Future Directions** | SVE/SVE2 not yet exploited by either compiler on Windows; MSVC ARM64 backend is actively improving (v14.44→v14.50 showed measurable gains) |
