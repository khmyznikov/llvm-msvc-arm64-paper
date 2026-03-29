# MSVC vs LLVM on Windows — Benchmarks

Automated build, benchmark, and profiling framework for comparing MSVC and LLVM (clang-cl) compiler output on Windows across five open-source projects. Supports both **x64** and **ARM64** platforms (ARM64 is the primary target).

## Projects

| Project | Source | Build System | Benchmark |
|---------|--------|-------------|-----------|
| **LAME MP3** | SVN r6531 | MSBuild (VS2019) | Encode WAV → MP3, 20 runs |
| **NumPy** | v2.4.1 | Meson | `count_nonzero` (1M elements) |
| **CPython** | v3.14.2 | MSBuild (PCBuild) | pyperformance (15 CPU-bound benchmarks) |
| **Custom strcmp** | Local | Direct cl/clang-cl | Byte-by-byte comparison, 3 runs |
| **x264** | stable | Direct cl/clang-cl | H.264 encode 720p, 3 runs |

## Prerequisites

- **Windows** machine (x64 or ARM64)
- **Visual Studio 2022** with C++ workload (MSVC ≥ 14.50); ARM64 tools needed for `--platform=arm64`
- **LLVM ≥ 21.x** with clang-cl and lld-link
- **Python 3.x** — recommended via [Python Manager](https://github.com/zooba/pymanager) (`winget install 9NQ7512CXL7T`)
  - ARM64 machines: `pymanager install 3.14-arm64` (native ARM64 Python)
  - x64 machines: `pymanager install 3.14`
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
    pymanager install 3.14         # x64 machine
    pymanager install 3.14-arm64   # ARM64 machine

# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. List all available tasks
inv --list

# 3. Build everything with both toolchains (x64 for verification)
inv fetch-all
inv build-all --toolchain=both --platform=x64

# 3b. Or build for ARM64 (primary target)
#inv build-all --toolchain=both --platform=arm64

# 4. Run all benchmarks
inv bench-all --platform=x64

# 5. Capture ETW profiles
inv profile-all
```

## Per-project commands

All build/bench/profile commands accept `--platform=x64` or `--platform=arm64` (default: arm64).

### LAME MP3

```bash
inv lame.fetch                          # SVN checkout r6531
inv lame.patch                          # Add ARM64 platform + configMS.h fix
inv lame.build --toolchain=msvc --platform=x64   # Build with MSVC for x64
inv lame.build --toolchain=llvm --platform=arm64  # Build with clang-cl for ARM64
inv lame.bench --toolchain=msvc         # Benchmark (20 encoding runs)
inv lame.profile --toolchain=msvc       # ETW CPU sampling trace
```

### NumPy

```bash
inv numpy.fetch                         # Git clone v2.4.1
inv numpy.build --toolchain=msvc        # Meson build with MSVC
inv numpy.build --toolchain=llvm        # Meson build with clang-cl
inv numpy.bench --toolchain=msvc        # count_nonzero benchmark
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

### Custom strcmp

```bash
inv strcmp.build --toolchain=both       # Build all 4 variants (msvc/llvm x inline/noinline)
inv strcmp.bench                        # Run all variants, 3 runs each
inv strcmp.profile --toolchain=msvc     # ETW trace of inline MSVC variant
inv strcmp.profile --toolchain=llvm --noinline  # ETW trace of noinline LLVM variant
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
├── strcmp/
│   └── strcmp_results.json
└── x264/
    └── x264_results.json
```

ETW traces (`.etl` files) are also saved to the respective results subdirectories.

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
│   ├── numpy/                    # NumPy count_nonzero
│   ├── cpython/                  # CPython pyperformance
│   ├── strcmp/                   # Custom strcmp benchmark
│   └── x264/                    # x264 H.264 encoder
├── results/                      # Benchmark output (gitignored)
└── sources/                      # Auto-fetched sources (gitignored)
```
