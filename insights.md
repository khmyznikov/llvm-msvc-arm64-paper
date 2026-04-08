# Insights: MSVC vs Clang/LLVM on Windows ARM64

Collected from benchmark runs on two ARM64 Windows machines:

| Machine | SoC | Cores | OS |
|---------|-----|-------|-----|
| **GLEB-DEVKIT** (Volterra) | Qualcomm Snapdragon 8cx Gen 3 | 8 | Windows 11 (10.0.27975) |
| **GLEB-SURFACE-15** | Qualcomm Snapdragon X Elite (X1E80100) | 12 | Windows 11 (10.0.26595) |

**Compilers tested**: MSVC v14.51 (VS 2026) on Volterra, MSVC v14.50 on Surface 15, vs LLVM/Clang 22.1.1 (clang-cl)

---

## 1. Summary of Results

### Volterra — Snapdragon 8cx Gen 3

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 1.143s mean | 0.810s mean | **+29.1% faster** |
| **NumPy sqrt** | 4.322ms mean | 4.209ms mean | **+2.6% faster** |
| **NumPy sort** | 82.28ms mean | 42.66ms mean | **+48.2% faster** |
| **x264** (H.264 encode) | 3.74 fps | 4.48 fps | **+19.6% faster** |
| **CPython** (geo-mean) | 76.32ms | 59.29ms | **+22.3% faster** |

### Surface Laptop 15 — Snapdragon X Elite (X1E80100)

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 0.599s mean | 0.402s mean | **+32.9% faster** |
| **NumPy sqrt** | 2.731ms mean | 2.113ms mean | **+22.6% faster** |
| **NumPy sort** | 63.18ms mean | 25.76ms mean | **+59.2% faster (2.5×)** |
| **x264** (H.264 encode) | 7.74 fps | 10.02 fps | **+29.4% faster** |
| **CPython** (geo-mean) | 49.79ms | 32.11ms | **+35.5% faster** |

**Overall finding**: LLVM/Clang produces **consistently and significantly faster code** than MSVC for ARM64 Windows across both platforms, with advantages ranging from **20% to 60%** depending on the workload. The Volterra now uses MSVC v14.51, while the Surface 15 uses v14.50. On the Volterra, v14.51 **significantly improved x264 codegen** (gap narrowed from 30% to 20%) but **reverted the dramatic sqrt optimization** from v14.50 (MSVC lost its 30% sqrt lead, now 2.6% slower than LLVM). On the Surface 15 (X Elite), the LLVM advantage remains consistently large (27–44% on CPython, 33% on LAME, 59% on sort). CPython on Volterra was not rebuilt with v14.51 (still compiled with v14.50).

---

## 2. Detailed Benchmark Data

### 2.1 LAME MP3 Encoder (SVN r6531)
- **Build system**: MSBuild (VS2019 solution), custom override props
- **Workload**: Encode WAV → MP3 with "extreme" preset, 20 runs

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 1.143s (min 1.128, max 1.165) | 0.810s (min 0.802, max 0.825) | +29.1% |
| Surface 15 (X Elite) | 0.599s (min 0.594, max 0.609) | 0.402s (min 0.395, max 0.413) | +32.9% |

- **Key insight**: LAME is a float-heavy, loop-intensive encoder. LLVM's ARM64 backend generates better instruction scheduling and vectorization for the core DCT/psychoacoustic model loops. LLVM also shows tighter variance (more consistent performance). On Volterra, MSVC v14.51 is slightly slower than v14.50 on this workload (1.143s vs 1.135s), continuing the regression trend from v14.44 (1.108s). On the Surface 15, MSVC v14.50 also regressed vs v14.44 (0.599s vs 0.576s), suggesting the newer compiler's optimizations don't uniformly benefit all code patterns on either microarchitecture.

### 2.2 NumPy (v2.4.1) — sqrt & sort
- **Build system**: Meson with native cross-files
- **Workload**: `sqrt` and `sort` on 1M-element float64 arrays, 50 runs each
- **Note**: Earlier benchmarks used `count_nonzero`, which was memory-bandwidth-bound on the faster X Plus chip and showed near-zero compiler difference. Switched to compute-intensive operations that exercise compiler codegen. On Volterra, MSVC v14.50 showed dramatically improved sqrt performance (2.936ms vs 4.968ms in v14.44), but **v14.51 reverted this gain** (back to 4.322ms), putting MSVC slightly behind LLVM again.

**sqrt (1M float64)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 4.322ms (min 4.229) | 4.209ms (min 4.111) | +2.6% |
| Surface 15 (X Elite) | 2.731ms (min 2.544) | 2.113ms (min 2.043) | +22.6% |

**sort (1M float64, quicksort)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 82.28ms (min 81.69) | 42.66ms (min 41.43) | +48.2% |
| Surface 15 (X Elite) | 63.18ms (min 61.79) | 25.76ms (min 25.61) | +59.2% (2.5×) |

- **Key insight**: `sort` is the standout result — LLVM generates dramatically better quicksort code on ARM64, with a 2.5× advantage on X Elite. `sqrt` reveals a striking version-sensitivity story: MSVC v14.50 **beat LLVM by 30%** on Volterra with a dramatically improved vectorization strategy, but **v14.51 reverted this** (now 2.6% slower than LLVM). On the X Elite, LLVM remains **22.6% faster** on sqrt regardless of MSVC version.

### 2.3 x264 H.264 Encoder (stable branch)
- **Build system**: Direct cl/clang-cl compilation (pure C, no hand-written ASM)
- **Workload**: Encode 300 frames of 720p YUV420 → H.264, medium preset, 3 runs

| Machine | MSVC mean fps | LLVM mean fps | LLVM Advantage |
|---------|---------------|---------------|----------------|
| Volterra (8cx Gen 3) | 3.74 (3.72–3.76) | 4.48 (4.47–4.48) | +19.6% |
| Surface 15 (X Elite) | 7.74 (7.70–7.77) | 10.02 (9.99–10.03) | +29.4% |

- **Key insight**: x264 is extremely compute-intensive with tight inner loops for motion estimation, DCT, quantization, and entropy coding. LLVM produces better ARM64 code for these patterns with all hand-written ASM disabled, isolating pure compiler codegen quality. MSVC v14.51 **significantly improved x264 codegen on Volterra**, narrowing the LLVM advantage from 29.7% (v14.50) to 19.6%. On the Surface 15 (still v14.50), the gap remains ~29%. This suggests v14.51 made genuine progress on tight loop optimization for the x264 workload.

### 2.4 CPython pyperformance (v3.14.2, 15 CPU-bound benchmarks)
- **Build system**: MSBuild (PCBuild)
- **Workload**: 15 CPU-bound pyperformance benchmarks with --rigorous (40 runs each)

**Volterra (Snapdragon 8cx Gen 3)** — LLVM geo-mean: 59.29ms, MSVC geo-mean: 76.32ms (**+22.3%**, CPython compiled with v14.50):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 125.28 | 95.43 | 23.8% |
| crypto_pyaes | 159.65 | 129.96 | 18.6% |
| deltablue | 7.65 | 5.37 | 29.8% |
| fannkuch | 799.22 | 664.08 | 16.9% |
| float | 143.86 | 112.44 | 21.8% |
| go | 239.54 | 169.25 | 29.3% |
| hexiom | 13.38 | 10.01 | 25.2% |
| nbody | 217.38 | 165.48 | 23.9% |
| pickle_pure_python | 0.78 | 0.56 | 27.5% |
| pidigits | 311.46 | 326.57 | −4.8% (MSVC faster) |
| pyflate | 909.70 | 722.03 | 20.6% |
| raytrace | 578.64 | 437.36 | 24.4% |
| richards | 98.58 | 68.92 | 30.1% |
| spectral_norm | 216.10 | 178.38 | 17.5% |
| unpickle_pure_python | 0.52 | 0.40 | 24.2% |

**Surface Laptop 15 (Snapdragon X Elite)** — LLVM geo-mean: 32.11ms, MSVC geo-mean: 49.79ms (**+35.5%**):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 80.57 | 48.15 | 40.2% |
| crypto_pyaes | 99.00 | 63.36 | 36.0% |
| deltablue | 5.43 | 3.08 | 43.2% |
| fannkuch | 487.59 | 354.06 | 27.4% |
| float | 96.84 | 63.61 | 34.3% |
| go | 179.05 | 100.69 | 43.8% |
| hexiom | 9.92 | 5.53 | 44.3% |
| nbody | 136.93 | 95.76 | 30.1% |
| pickle_pure_python | 0.43 | 0.26 | 41.2% |
| pidigits | 197.56 | 249.40 | −26.2% (MSVC faster) |
| pyflate | 590.60 | 391.45 | 33.7% |
| raytrace | 357.96 | 214.37 | 40.1% |
| richards | 66.82 | 40.38 | 39.6% |
| spectral_norm | 143.00 | 85.43 | 40.3% |
| unpickle_pure_python | 0.33 | 0.19 | 42.5% |

- **Key insight**: LLVM is faster on 14 out of 15 benchmarks on both machines. The sole exception is **pidigits** (bignum arithmetic via GMP/libmpz) where MSVC is faster — with a 26.2% advantage on the X Elite (vs 4.8% on Volterra). The CPython interpreter on Volterra was not rebuilt with MSVC v14.51 (still compiled with v14.50), so CPython results are unchanged. The Surface 15 consistently shows a **larger LLVM advantage** (27–44%) than Volterra (17–30%), confirming this is a genuine **microarchitecture effect**: the Oryon cores in the X Elite benefit more from LLVM's code generation than the older Kryo cores.

---

## 3. Cross-Platform Comparison

The Volterra uses MSVC v14.51 (except CPython, still v14.50), while the Surface 15 uses v14.50. The Surface Laptop 15 (X Elite, 12 cores) is roughly **1.8–2× faster** than the Volterra (8cx Gen 3, 8 cores) in absolute terms across all benchmarks. The **LLVM advantage is consistently larger on the newer X Elite chip**:

| Benchmark | 8cx Gen 3 LLVM adv. | X Elite LLVM adv. |
|-----------|---------------------|------------------|
| LAME MP3 | +29.1% | +32.9% |
| NumPy sqrt | +2.6% | +22.6% |
| NumPy sort | +48.2% | +59.2% |
| x264 | +19.6% | +29.4% |
| CPython (geo) | +22.3% | +35.5% |

The most notable cross-platform finding is **x264**: MSVC v14.51 on Volterra narrowed the gap to 19.6% (from 29.7% with v14.50), while the Surface 15 (still v14.50) shows 29.4% — this suggests v14.51 made genuine improvements to tight-loop codegen. **NumPy sqrt** is no longer a cross-platform anomaly: v14.51 reverted the v14.50 sqrt optimization, so both machines now show LLVM as faster on sqrt (2.6% on Volterra, 22.6% on X Elite). CPython shows a clear microarchitecture effect: the LLVM advantage grows from 22% (Kryo) to 36% (Oryon), suggesting LLVM's code generation aligns better with the newer out-of-order execution pipeline.

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
- **NumPy**: Meson build with native cross-files (`.ini`) works for both toolchains. No BLAS/LAPACK (built with internal fallback). Original `count_nonzero` benchmark was memory-bandwidth-bound on the X Elite, showing near-zero compiler difference. Switched to `sqrt` and `sort` which are compute-bound. MSVC v14.50 showed dramatically improved sqrt on Volterra (beating LLVM by 30%), but **v14.51 reverted this gain** (now 2.6% behind LLVM). Sort remains heavily LLVM-favored across all versions.
- **CPython**: Both toolchains produce working Python interpreters. The LLVM-built CPython runs pyperformance benchmarks 22–36% faster depending on the machine. CPython on Volterra was not rebuilt with MSVC v14.51 (still using v14.50-compiled interpreter), so CPython results there are unchanged. On the Surface 15, v14.50 showed no improvement over v14.44.
- **x264**: Built from source with handcrafted `config.h` (no autotools/MSYS2). x264's unity build pattern (`.c` files `#include`-ing other `.c` files) requires careful source file management. All hand-written ASM disabled to isolate compiler codegen quality.

---

## 6. Architecture-Specific Observations

### 6.1 ARM64 Code Generation Quality
- LLVM's ARM64 (AArch64) backend has benefited from years of optimization for server and mobile ARM targets (Linux, Android, macOS/Apple Silicon). This maturity shows in consistently better instruction selection and scheduling.
- MSVC's ARM64 backend has seen **mixed results across versions** on the **Volterra** (8cx Gen 3):
  - v14.50: NumPy sqrt went from 14% slower to **30% faster** than LLVM, x264 gap narrowed from 44% to 30%
  - **v14.51: Reverted the sqrt optimization** (back to 2.6% slower than LLVM), but **further improved x264** (gap narrowed from 30% to 20%)
  - This pattern of gains and regressions across versions suggests MSVC's ARM64 optimizer is still maturing, with changes that improve one workload sometimes hurting another
- On the **Surface 15** (X Elite), v14.50 showed **marginal regressions** vs v14.44:
  - LAME: 0.576s → 0.599s (+4% slower)
  - CPython geo-mean: 48.78ms → 49.79ms (+2% slower)
  - NumPy sqrt: 2.667ms → 2.731ms (still behind LLVM by 23%)
  - This suggests v14.50's optimizations are tuned for the older Kryo microarchitecture and may not translate to the newer Oryon cores
- For complex branching patterns (sort: 48–59% gap) and interpreter dispatch (22–36% gap), LLVM still leads significantly on both platforms

### 6.2 Microarchitecture Sensitivity
- With the Volterra on MSVC v14.51 and Surface 15 on v14.50, cross-platform comparisons must account for the version difference. However, the **LLVM advantage remains consistently larger on the X Elite** (Oryon) than on the 8cx Gen 3 (Kryo) across all workloads.
- NumPy sqrt is no longer the dramatic cross-platform anomaly it was with v14.50: after v14.51 reverted the sqrt optimization, both machines now show LLVM as faster (2.6% on Volterra, 22.6% on X Elite).
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
| OS | Windows 11 (10.0.27975) | Windows 11 (10.0.26595) |

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
| **4. Runtime Performance** | 20–60% advantage for LLVM on most workloads; MSVC v14.51 improved x264 but regressed on sqrt |
| **5. Platform Features** | MSVC offers ARM64EC (not tested); Clang offers cross-platform consistency |
| **6. Developer Experience** | MSVC setup has gaps (vswhere, vcvarsall issues); clang-cl flag syntax is confusing but functional |
| **7. Use Cases** | Audio/video encoding, numerical computing, language runtimes all favor LLVM |
| **8. Limitations** | MSVC is Windows-only; LLVM is open-source; some projects (Blender) only support specific toolchains |
| **9. Methodology** | 4 real-world projects, 2 ARM64 machines, CPU-pinned, high-priority, multiple runs, structured JSON output |
| **10. Future Directions** | SVE/SVE2 not yet exploited by either compiler on Windows; MSVC ARM64 backend is actively improving but inconsistently (v14.44→v14.50→v14.51 showed gains on some workloads and regressions on others, suggesting ongoing optimization instability) |
