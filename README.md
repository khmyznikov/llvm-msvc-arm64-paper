# MSVC vs LLVM on Windows — Benchmarks

Automated build, benchmark, and profiling framework for comparing MSVC and LLVM (clang-cl) compiler output on **Windows ARM64** across four open-source projects.

## Projects

| Project | Source | Build System | Benchmark |
|---------|--------|-------------|-----------|
| **LAME MP3** | SVN r6531 | MSBuild (VS2019) | Encode WAV → MP3, 20 runs |
| **NumPy** | v2.4.1 | Meson | `sqrt`, `sort` (1M elements, 50 runs) |
| **CPython** | v3.14.2 | MSBuild (PCBuild) | pyperformance (15 CPU-bound benchmarks) |
| **x264** | stable | Direct cl/clang-cl | H.264 encode 720p, 3 runs |

## Prerequisites

- **Windows ARM64** machine
- **Visual Studio 2026** (or 2022) with C++ workload (MSVC ≥ 14.50) and ARM64 tools
- **LLVM ≥ 21.x** with clang-cl and lld-link
- **ClangCL MSBuild toolset** — required for LLVM builds of MSBuild projects (LAME, CPython). Install via VS Installer → Individual components → *C++ Clang Compiler for Windows* + *MSBuild support for LLVM (clang-cl) toolset*
- **Python 3.x** (native ARM64) — recommended via [Python Manager](https://github.com/zooba/pymanager) (`winget install 9NQ7512CXL7T`)
  - `pymanager install 3.14-arm64`
- **Git**, **SVN** (for LAME), **Meson**, **Ninja**, **CMake**
- **Windows Performance Toolkit** (xperf) for profiling
- **PowerShell 7+** — required to run `setup_env.ps1`
  ```powershell
  winget install --id Microsoft.PowerShell --source winget
  ```
  VS Code users: install the [PowerShell extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode.PowerShell)

### Validate environment

```powershell
.\setup_env.ps1           # Check all tools
.\setup_env.ps1 -Install  # Auto-install missing tools via winget
```

> **Execution policy error?** If you see `running scripts is disabled on this system`, use one of these workarounds:
>
> ```powershell
> # Option A: allow local scripts for current user (recommended, persistent)
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
>
> # Option B: bypass for this session only
> Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
>
> # Option C: run the script directly without changing policy
> pwsh -ExecutionPolicy Bypass -File .\setup_env.ps1
> ```

## Quick start

```pwsh
# 0. Install Python via Python Manager (recommended)
    winget install 9NQ7512CXL7T
    pymanager install 3.14-arm64

# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. List all available tasks
inv --list

# 3. Build everything with both toolchains
inv fetch-all
inv build-all --toolchain=both

# 4. Run all benchmarks
inv bench-all

# 5. Capture ETW profiles
inv profile-all
```

## Per-project commands

### LAME MP3

```bash
inv lame.fetch                          # SVN checkout r6531
inv lame.patch                          # Add ARM64 platform + configMS.h fix
inv lame.build --toolchain=msvc         # Build with MSVC for ARM64
inv lame.build --toolchain=llvm         # Build with clang-cl for ARM64
inv lame.bench --toolchain=msvc         # Benchmark (20 encoding runs)
inv lame.profile --toolchain=msvc       # ETW CPU sampling trace
```

### NumPy

```bash
inv numpy.fetch                         # Git clone v2.4.1
inv numpy.build --toolchain=msvc        # Meson build with MSVC
inv numpy.build --toolchain=llvm        # Meson build with clang-cl
inv numpy.bench --toolchain=msvc        # sqrt + sort benchmark
inv numpy.profile --toolchain=msvc      # ETW trace
```

### CPython

```bash
inv cpython.fetch                       # Git clone v3.14.2 + externals
inv cpython.patch                       # Copy profiling props to PCbuild
inv cpython.build --toolchain=msvc      # Non-PGO build
inv cpython.build --toolchain=msvc --pgo  # PGO build
inv cpython.build --toolchain=llvm      # clang-cl build
inv cpython.bench --toolchain=msvc      # pyperformance (all 112 benchmarks)
inv cpython.bench --toolchain=msvc --fast  # CPU-bound subset (15 benchmarks)
inv cpython.profile --toolchain=msvc --benchmark=deltablue  # ETW trace
```

### x264 (H.264 encoder)

```bash
inv x264.fetch                          # Clone x264 stable branch
inv x264.build --toolchain=both         # Build with MSVC and clang-cl (pure C, no ASM)
inv x264.bench                          # Encode 720p YUV, 3 runs each toolchain
inv x264.profile --toolchain=msvc       # ETW trace
```

## Results

Benchmark results are saved to `results/` as JSON files:

```
results/
├── lame/
│   ├── lame_msvc.json
│   └── lame_llvm.json
├── numpy/
│   ├── numpy_msvc.json
│   └── numpy_llvm.json
├── cpython/
│   ├── pyperformance_msvc.json
│   ├── pyperformance_llvm.json
│   ├── pyperformance_msvc_pgo.json
│   └── pyperformance_llvm_pgo.json
└── x264/
    └── x264_results.json
```

ETW traces (`.etl` files) are also saved to the respective results subdirectories.

## Generate Excel charts

After running benchmarks on one or more machines, generate a comparison workbook:

```bash
python generate_excel_charts.py
```

This reads all JSON results from `results/` and produces `results/performance_comparison.xlsx` with:
- **Overview** — summary table across all benchmarks and machines
- **Overview Chart** — absolute performance bar charts
- **LLVM Advantage %** — relative speedup chart
- **Per-project sheets** — LAME, x264, NumPy, CPython detail with charts
- **Speedup Ratio** — LLVM/MSVC ratio chart

## Compiler flags

| | MSVC | LLVM (clang-cl) |
|---|------|-----------------|
| **Optimization** | `/O2` | `-O3` |
| **LTO** | `/GL` + `/LTCG` | `-flto` + `-fuse-ld=lld` |
| **Fast math** | `/fp:fast` | `-ffast-math` |
| **Security** | `/GS-` | `/GS-` |

## Profiling

ETW CPU sampling traces are captured using `xperf` from Windows Performance Toolkit. Frame pointers are enabled (`/Oy-` for MSVC, `-fno-omit-frame-pointer` for clang-cl) to support ETW stack walking.

Analyze traces with [Profile Explorer](https://github.com/niclaslindstedt/profile-explorer) or Windows Performance Analyzer (WPA).

## Directory structure

```
├── setup_env.ps1                 # Environment validation
├── tasks.py                      # Root Invoke orchestrator
├── invoke.yaml                   # Invoke config
├── requirements.txt              # Python dependencies
├── common/
│   ├── config.py                 # Central config (versions, flags, paths)
│   ├── toolchain.py              # MSVC/LLVM detection helpers
│   └── profiling.py              # ETW/xperf wrappers
├── benchmarks/
│   ├── lame/                     # LAME MP3 encoder
│   ├── numpy/                    # NumPy sqrt & sort
│   ├── cpython/                  # CPython pyperformance
│   └── x264/                    # x264 H.264 encoder
├── results/                      # Benchmark output (gitignored)
└── sources/                      # Auto-fetched sources (gitignored)
```
