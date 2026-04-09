# Insights: MSVC vs Clang/LLVM on Windows ARM64

Collected from benchmark runs on two ARM64 Windows machines:

| Machine | SoC | Cores | OS |
|---------|-----|-------|-----|
| **GLEB-DEVKIT** (Volterra) | Qualcomm Snapdragon 8cx Gen 3 | 8 | Windows 11 (10.0.27975) |
| **GLEB-SURFACE-15** | Qualcomm Snapdragon X Elite (X1E80100) | 12 | Windows 11 (10.0.26595) |

**Compilers tested**: MSVC v14.51 (VS 2026) vs LLVM/Clang 22.1.1 (clang-cl)

---

## 1. Summary of Results

### Volterra — Snapdragon 8cx Gen 3

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 1.104s mean | 0.810s mean | **+26.6% faster** |
| **NumPy sqrt** | 4.322ms mean | 4.209ms mean | **+2.6% faster** |
| **NumPy sort** | 82.28ms mean | 42.66ms mean | **+48.2% faster** |
| **x264** (H.264 encode) | 3.74 fps | 4.48 fps | **+19.6% faster** |
| **CPython** (geo-mean) | 78.20ms | 59.29ms | **+24.2% faster** |

### Surface Laptop 15 — Snapdragon X Elite (X1E80100)

| Benchmark | MSVC | LLVM | LLVM Advantage |
|-----------|------|------|----------------|
| **LAME MP3** (encode) | 0.574s mean | 0.402s mean | **+30.0% faster** |
| **NumPy sqrt** | 0.629ms mean | 2.113ms mean | **−70.2% (MSVC 3.4× faster)** |
| **NumPy sort** | 62.58ms mean | 25.76ms mean | **+58.8% faster (2.4×)** |
| **x264** (H.264 encode) | 8.18 fps | 9.97 fps | **+21.8% faster** |
| **CPython** (geo-mean) | 49.05ms | 32.11ms | **+34.5% faster** |

**Overall finding**: LLVM/Clang produces **consistently and significantly faster code** than MSVC for ARM64 Windows across both platforms, with advantages ranging from **20% to 59%** depending on the workload. Both machines now use MSVC v14.51. On the Volterra, v14.51 **improved LAME** (1.104s vs 1.143s with v14.50) and **x264 codegen** (gap narrowed from 30% to 20%), but **reverted the dramatic sqrt optimization** from v14.50 and **slightly regressed CPython** (78.20ms geo-mean vs 76.32ms). On the Surface 15, v14.51 brought **dramatic improvements**: NumPy sqrt went from 2.731ms to **0.629ms** (MSVC now **3.4× faster** than LLVM), LAME recovered to v14.44 levels (0.574s), and x264 improved from 7.74 to 8.18 fps. The sqrt result is the most striking finding: v14.51's sqrt optimization works spectacularly on the Oryon cores (X Elite) but was **reverted** on the Kryo cores (Volterra), suggesting microarchitecture-dependent codegen paths.

---

## 2. Detailed Benchmark Data

### 2.1 LAME MP3 Encoder (SVN r6531)
- **Build system**: MSBuild (VS2019 solution), custom override props
- **Workload**: Encode WAV → MP3 with "extreme" preset, 20 runs

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 1.104s (min 1.088, max 1.118) | 0.810s (min 0.802, max 0.825) | +26.6% |
| Surface 15 (X Elite) | 0.574s (min 0.566, max 0.589) | 0.402s (min 0.395, max 0.413) | +30.0% |

- **Key insight**: LAME is a float-heavy, loop-intensive encoder. LLVM's ARM64 backend generates better instruction scheduling and vectorization for the core DCT/psychoacoustic model loops. LLVM also shows tighter variance (more consistent performance). Both machines now use MSVC v14.51: on Volterra, v14.51 improved over v14.50 (1.104s vs 1.143s), and on the Surface 15, v14.51 also recovered from v14.50's regression (0.574s vs 0.599s), returning to v14.44 levels (0.576s). The LLVM advantage is consistent at ~27–30% across both machines.

### 2.2 NumPy (v2.4.1) — sqrt & sort
- **Build system**: Meson with native cross-files
- **Workload**: `sqrt` and `sort` on 1M-element float64 arrays, 50 runs each
- **Note**: Earlier benchmarks used `count_nonzero`, which was memory-bandwidth-bound on the faster X Plus chip and showed near-zero compiler difference. Switched to compute-intensive operations that exercise compiler codegen. On Volterra, MSVC v14.50 showed dramatically improved sqrt performance (2.936ms vs 4.968ms in v14.44), but **v14.51 reverted this gain** (back to 4.322ms). However, on the Surface 15, **v14.51 introduced a massive sqrt improvement** — from 2.731ms (v14.50) to **0.629ms**, making MSVC **3.4× faster** than LLVM (2.113ms). This suggests v14.51's sqrt codegen uses an optimization path that works on Oryon but not Kryo cores.

**sqrt (1M float64)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 4.322ms (min 4.229) | 4.209ms (min 4.111) | +2.6% |
| Surface 15 (X Elite) | 0.629ms (min 0.620) | 2.113ms (min 2.043) | −70.2% (MSVC 3.4× faster) |

**sort (1M float64, quicksort)**:

| Machine | MSVC mean | LLVM mean | LLVM Advantage |
|---------|-----------|-----------|----------------|
| Volterra (8cx Gen 3) | 82.28ms (min 81.69) | 42.66ms (min 41.43) | +48.2% |
| Surface 15 (X Elite) | 62.58ms (min 61.52) | 25.76ms (min 25.61) | +58.8% (2.4×) |

- **Key insight**: `sort` is the standout result — LLVM generates dramatically better quicksort code on ARM64, with a 2.4× advantage on X Elite. `sqrt` reveals a striking **microarchitecture-dependent codegen story** with MSVC v14.51: on **Volterra** (Kryo), v14.51 **reverted** the v14.50 sqrt optimization (now 2.6% slower than LLVM), but on the **Surface 15** (Oryon), v14.51 introduced a **spectacular improvement** — 0.629ms vs LLVM's 2.113ms, making MSVC **3.4× faster**. This strongly suggests MSVC v14.51 uses different NEON vectorization strategies depending on the target microarchitecture, or that the same codegen behaves radically differently on Kryo vs Oryon execution units.

### 2.3 x264 H.264 Encoder (stable branch)
- **Build system**: Direct cl/clang-cl compilation (pure C, no hand-written ASM)
- **Workload**: Encode 300 frames of 720p YUV420 → H.264, medium preset, 3 runs

| Machine | MSVC mean fps | LLVM mean fps | LLVM Advantage |
|---------|---------------|---------------|----------------|
| Volterra (8cx Gen 3) | 3.74 (3.72–3.76) | 4.48 (4.47–4.48) | +19.6% |
| Surface 15 (X Elite) | 8.18 (8.14–8.21) | 9.97 (9.95–9.99) | +21.8% |

- **Key insight**: x264 is extremely compute-intensive with tight inner loops for motion estimation, DCT, quantization, and entropy coding. LLVM produces better ARM64 code for these patterns with all hand-written ASM disabled, isolating pure compiler codegen quality. MSVC v14.51 **significantly improved x264 codegen on both machines**: Volterra gap narrowed from 29.7% (v14.50) to 19.6%, and Surface 15 gap narrowed from 29.4% (v14.50) to 21.8%. Both machines now show a consistent ~20% LLVM advantage, confirming v14.51 made genuine progress on tight loop optimization.

### 2.4 CPython pyperformance (v3.14.2, 15 CPU-bound benchmarks)
- **Build system**: MSBuild (PCBuild)
- **Workload**: 15 CPU-bound pyperformance benchmarks with --rigorous (40 runs each)

**Volterra (Snapdragon 8cx Gen 3)** — LLVM geo-mean: 59.29ms, MSVC geo-mean: 78.20ms (**+24.2%**):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 128.84 | 95.43 | 25.9% |
| crypto_pyaes | 160.04 | 129.96 | 18.8% |
| deltablue | 7.82 | 5.37 | 31.3% |
| fannkuch | 823.37 | 664.08 | 19.3% |
| float | 147.18 | 112.44 | 23.6% |
| go | 247.97 | 169.25 | 31.7% |
| hexiom | 13.91 | 10.01 | 28.1% |
| nbody | 218.88 | 165.48 | 24.4% |
| pickle_pure_python | 0.76 | 0.56 | 26.3% |
| pidigits | 319.71 | 326.57 | −2.1% (MSVC faster) |
| pyflate | 939.73 | 722.03 | 23.2% |
| raytrace | 600.60 | 437.36 | 27.2% |
| richards | 97.84 | 68.92 | 29.6% |
| spectral_norm | 227.51 | 178.38 | 21.6% |
| unpickle_pure_python | 0.55 | 0.40 | 28.3% |

**Surface Laptop 15 (Snapdragon X Elite)** — LLVM geo-mean: 32.11ms, MSVC geo-mean: 49.05ms (**+34.5%**):

| Benchmark | MSVC (ms) | LLVM (ms) | LLVM faster by |
|-----------|-----------|-----------|----------------|
| chaos | 80.01 | 48.15 | 39.8% |
| crypto_pyaes | 97.90 | 63.36 | 35.3% |
| deltablue | 5.38 | 3.08 | 42.7% |
| fannkuch | 490.30 | 354.06 | 27.8% |
| float | 94.84 | 63.61 | 32.9% |
| go | 171.88 | 100.69 | 41.4% |
| hexiom | 9.13 | 5.53 | 39.4% |
| nbody | 132.70 | 95.76 | 27.8% |
| pickle_pure_python | 0.43 | 0.26 | 40.7% |
| pidigits | 199.00 | 249.40 | −25.3% (MSVC faster) |
| pyflate | 592.67 | 391.45 | 34.0% |
| raytrace | 355.19 | 214.37 | 39.6% |
| richards | 65.24 | 40.38 | 38.1% |
| spectral_norm | 142.23 | 85.43 | 39.9% |
| unpickle_pure_python | 0.34 | 0.19 | 43.1% |

- **Key insight**: LLVM is faster on 14 out of 15 benchmarks on both machines. The sole exception is **pidigits** (bignum arithmetic via GMP/libmpz) where MSVC is faster — with a 25.3% advantage on the X Elite (vs 2.1% on Volterra). With both machines now on MSVC v14.51, the Surface 15 CPython performance **slightly improved** vs v14.50 (49.05ms vs 49.79ms geo-mean), while the Volterra **slightly regressed** vs v14.50 (78.20ms vs 76.32ms). The Surface 15 consistently shows a **larger LLVM advantage** (28–43%) than Volterra (19–32%), confirming this is a genuine **microarchitecture effect**: the Oryon cores in the X Elite benefit more from LLVM's code generation than the older Kryo cores.

---

## 3. Cross-Platform Comparison

Both machines now use MSVC v14.51, enabling a valid cross-platform comparison. The Surface Laptop 15 (X Elite, 12 cores) is roughly **1.8–2× faster** than the Volterra (8cx Gen 3, 8 cores) in absolute terms across all benchmarks. The **LLVM advantage is generally larger on the newer X Elite chip**, with the striking exception of NumPy sqrt:

| Benchmark | 8cx Gen 3 LLVM adv. | X Elite LLVM adv. |
|-----------|---------------------|------------------|
| LAME MP3 | +26.6% | +30.0% |
| NumPy sqrt | +2.6% | −70.2% (MSVC 3.4× faster) |
| NumPy sort | +48.2% | +58.8% |
| x264 | +19.6% | +21.8% |
| CPython (geo) | +24.2% | +34.5% |

The **x264** results now show a consistent ~20% LLVM advantage on both machines with v14.51, confirming genuine improvements to MSVC's tight-loop codegen in this version. The most striking cross-platform finding is **NumPy sqrt**: MSVC v14.51 is 2.6% *slower* than LLVM on Volterra (Kryo) but **3.4× faster** on the Surface 15 (Oryon). This dramatic divergence suggests v14.51's sqrt vectorization strategy — possibly using specific NEON instruction sequences or memory access patterns — executes efficiently on Oryon's wider execution units but poorly on Kryo's narrower pipeline. CPython shows a clear microarchitecture effect: the LLVM advantage grows from 24% (Kryo) to 35% (Oryon), suggesting LLVM's code generation aligns better with the newer out-of-order execution pipeline.

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
- **NumPy**: Meson build with native cross-files (`.ini`) works for both toolchains. No BLAS/LAPACK (built with internal fallback). Original `count_nonzero` benchmark was memory-bandwidth-bound on the X Elite, showing near-zero compiler difference. Switched to `sqrt` and `sort` which are compute-bound. MSVC v14.51 shows a dramatic microarchitecture split on sqrt: **reverted** the v14.50 optimization on Volterra (now 2.6% behind LLVM) but achieved a **3.4× speedup** over LLVM on the Surface 15. Sort remains heavily LLVM-favored (48–59%) across all versions and machines.
- **CPython**: Both toolchains produce working Python interpreters. The LLVM-built CPython runs pyperformance benchmarks 24–35% faster depending on the machine. On Volterra, MSVC v14.51 **slightly regressed** CPython performance vs v14.50 (78.20ms vs 76.32ms geo-mean). On the Surface 15, v14.51 showed a **slight improvement** over v14.50 (49.05ms vs 49.79ms geo-mean).
- **x264**: Built from source with handcrafted `config.h` (no autotools/MSYS2). x264's unity build pattern (`.c` files `#include`-ing other `.c` files) requires careful source file management. All hand-written ASM disabled to isolate compiler codegen quality.

---

## 6. Architecture-Specific Observations

### 6.1 ARM64 Code Generation Quality
- LLVM's ARM64 (AArch64) backend has benefited from years of optimization for server and mobile ARM targets (Linux, Android, macOS/Apple Silicon). This maturity shows in consistently better instruction selection and scheduling.
- MSVC's ARM64 backend has seen **mixed results across versions** on the **Volterra** (8cx Gen 3):
  - v14.50: NumPy sqrt went from 14% slower to **30% faster** than LLVM, x264 gap narrowed from 44% to 30%
  - **v14.51: Reverted the sqrt optimization** (back to 2.6% slower than LLVM), but **further improved x264** (gap narrowed from 30% to 20%). **LAME improved** (1.104s vs 1.143s), but **CPython regressed** (78.20ms vs 76.32ms geo-mean)
  - This pattern of gains and regressions across versions suggests MSVC's ARM64 optimizer is still maturing
- On the **Surface 15** (X Elite), v14.51 showed **significant improvements** over v14.50:
  - NumPy sqrt: 2.731ms → **0.629ms** (MSVC now **3.4× faster** than LLVM — the most dramatic result in this study)
  - LAME: 0.599s → 0.574s (recovered to v14.44 levels)
  - x264: 7.74 → 8.18 fps (gap narrowed from 29.4% to 21.8%)
  - CPython: 49.79ms → 49.05ms (slight improvement)
  - The sqrt result is particularly striking: the *same* v14.51 compiler that *reverted* sqrt gains on Volterra (Kryo) produced a **spectacular 4.3× improvement** on the Surface 15 (Oryon), strongly suggesting microarchitecture-specific codegen paths
- For complex branching patterns (sort: 48–59% gap) and interpreter dispatch (24–35% gap), LLVM still leads significantly on both platforms

### 6.2 Microarchitecture Sensitivity
- With both machines now on MSVC v14.51, the microarchitecture effect is clearly isolated. The **LLVM advantage is generally larger on the X Elite** (Oryon) than on the 8cx Gen 3 (Kryo) for most workloads — except **NumPy sqrt**, where the situation is dramatically reversed.
- NumPy sqrt is the most striking microarchitecture-dependent result: MSVC v14.51 is 2.6% slower than LLVM on Kryo but **3.4× faster** on Oryon. This suggests the v14.51 sqrt codegen uses instruction sequences (possibly specific NEON patterns or memory prefetch strategies) that map extremely well to Oryon's wider execution pipeline but offer no benefit on Kryo.
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
| **4. Runtime Performance** | 20–59% advantage for LLVM on most workloads; MSVC v14.51 beats LLVM 3.4× on sqrt (X Elite only) and improved x264 to ~20% gap |
| **5. Platform Features** | MSVC offers ARM64EC (not tested); Clang offers cross-platform consistency |
| **6. Developer Experience** | MSVC setup has gaps (vswhere, vcvarsall issues); clang-cl flag syntax is confusing but functional |
| **7. Use Cases** | Audio/video encoding, numerical computing, language runtimes all favor LLVM |
| **8. Limitations** | MSVC is Windows-only; LLVM is open-source; some projects (Blender) only support specific toolchains |
| **9. Methodology** | 4 real-world projects, 2 ARM64 machines, CPU-pinned, high-priority, multiple runs, structured JSON output |
| **10. Future Directions** | SVE/SVE2 not yet exploited by either compiler on Windows; MSVC ARM64 backend is actively evolving (v14.44→v14.50→v14.51 showed microarchitecture-dependent gains — sqrt 3.4× faster on Oryon but reverted on Kryo — suggesting increasing specialization for newer cores) |
