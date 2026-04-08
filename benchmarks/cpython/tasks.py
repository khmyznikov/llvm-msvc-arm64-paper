"""Invoke tasks for CPython benchmark (pyperformance + pybench)."""

import json
import shutil
import subprocess
import time
from pathlib import Path

from invoke import task

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common import config
from common.toolchain import get_toolchain_env, find_clangcl
from common.profiling import profile_command

CPYTHON_SRC = config.SOURCES_DIR / "cpython"
BUILD_DIR = config.BUILD_DIR / "cpython"
RESULTS_DIR = config.RESULTS_DIR / "cpython"
ASSETS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------

@task
def fetch(c):
    """Clone CPython from GitHub at tag v3.14.2 and fetch externals."""
    if CPYTHON_SRC.exists():
        print(f"[cpython] Source already exists at {CPYTHON_SRC}")
    else:
        config.SOURCES_DIR.mkdir(parents=True, exist_ok=True)
        c.run(
            f'git clone --depth 1 --branch {config.CPYTHON_TAG} '
            f'"{config.CPYTHON_GIT_URL}" "{CPYTHON_SRC}"'
        )
        print(f"[cpython] Cloned {config.CPYTHON_TAG} to {CPYTHON_SRC}")

    # Fetch external dependencies (OpenSSL, Tcl/Tk, etc.)
    externals_bat = CPYTHON_SRC / "PCbuild" / "get_externals.bat"
    if externals_bat.exists():
        print("[cpython] Fetching external dependencies...")
        c.run(f'"{externals_bat}"', warn=True)


@task(pre=[fetch])
def patch(c):
    """Apply profiling support patches to CPython PCbuild/."""
    marker = CPYTHON_SRC / ".bench_patched"
    if marker.exists():
        print("[cpython] Already patched.")
        return

    pcbuild = CPYTHON_SRC / "PCbuild"

    # Copy msbuild.rsp for frame pointer / debug info support
    shutil.copy2(str(ASSETS_DIR / "msbuild.rsp"), str(pcbuild / "msbuild.rsp"))

    # Patch upstream pyproject-clangcl.props in-place:
    # - add -clang:-fno-omit-frame-pointer for ETW stack walking
    # - add -Wno-incompatible-pointer-types for Clang 21+ compat (socketmodule.c)
    clangcl_props = pcbuild / "pyproject-clangcl.props"
    if clangcl_props.exists():
        text = clangcl_props.read_text(encoding="utf-8")
        modified = False

        # Add frame pointer flag (using -clang: prefix for clang-cl)
        frame_ptr_flag = "-clang:-fno-omit-frame-pointer"
        if frame_ptr_flag not in text:
            # Append to the first unconditional AdditionalOptions line
            text = text.replace(
                "-Wno-unused-function %(AdditionalOptions)",
                f"-Wno-unused-function {frame_ptr_flag} %(AdditionalOptions)",
            )
            modified = True

        # Suppress -Wincompatible-pointer-types (Clang 21+ treats as error)
        # Note: upstream has -Wno-incompatible-pointer-types-discards-qualifiers
        # which is a *different* warning — we need the broader one too
        incompat_flag = "-Wno-incompatible-pointer-types "
        if incompat_flag not in text:
            text = text.replace(
                "-Wno-incompatible-pointer-types-discards-qualifiers",
                f"-Wno-incompatible-pointer-types-discards-qualifiers {incompat_flag}",
            )
            modified = True

        if modified:
            clangcl_props.write_text(text, encoding="utf-8")
            print("[cpython] Patched pyproject-clangcl.props: frame pointers + clang 21 compat")

    marker.write_text("patched")
    print("[cpython] Profiling patches applied to PCbuild/.")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_cmd(toolchain, pgo=False):
    """Construct the PCbuild/build.bat command."""
    pinfo = config.platform_info()
    build_bat = CPYTHON_SRC / "PCbuild" / "build.bat"
    cmd = f'"{build_bat}" -c Release -p {pinfo["msbuild"]}'
    if pgo:
        cmd += " --pgo"
    if toolchain == "llvm":
        clangcl = find_clangcl()
        llvm_dir = clangcl.parent.parent  # e.g. C:\Program Files\LLVM
        cmd += f' "/p:PlatformToolset=ClangCL"'
        cmd += f' "/p:LLVMInstallDir={llvm_dir}"'
        # Auto-detect LLVM tools version
        lib_clang = Path(str(llvm_dir)) / "lib" / "clang"
        if lib_clang.exists():
            versions = sorted(lib_clang.iterdir(), reverse=True)
            if versions:
                cmd += f' "/p:LLVMToolsVersion={versions[0].name}"'
    else:
        # Retarget from CPython's default toolset (v143/VS2022) to current VS
        cmd += ' "/p:PlatformToolset=v145"'
        if getattr(config, 'MSVC_PREVIEW_TOOLSET', False):
            cmd += ' "/p:MSVCPreviewEnabled=true"'
    return cmd


def _output_dir(toolchain, pgo=False):
    suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"
    return BUILD_DIR / suffix


@task(
    pre=[patch],
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "pgo": "Enable PGO build (default: False)",
    },
)
def build(c, toolchain="msvc", pgo=False):
    """Build CPython with the specified toolchain (ARM64)."""
    pinfo = config.platform_info()
    env = get_toolchain_env(toolchain)
    cmd = _build_cmd(toolchain, pgo)

    print(f"[cpython] Building ({toolchain}/arm64, PGO={pgo})...")

    # Clean previous PCbuild output for a fresh build
    pcbuild_out = CPYTHON_SRC / "PCbuild" / pinfo["pcbuild"]
    if pcbuild_out.exists():
        print(f"[cpython] Removing previous PCbuild output: {pcbuild_out}")
        shutil.rmtree(pcbuild_out)

    subprocess.run(cmd, shell=True, env=env, cwd=str(CPYTHON_SRC), check=True)

    # CPython outputs to PCbuild/<platform>/
    python_exe = pcbuild_out / "python.exe"
    if not python_exe.exists():
        print(f"[cpython] Warning: python.exe not found at {python_exe}")
        print(f"[cpython] Check PCbuild output in {pcbuild_out}")
        return

    # Create a proper installation via PC.layout (standalone binary layout)
    out_dir = _output_dir(toolchain, pgo)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    print(f"[cpython] Creating layout installation at {out_dir}...")
    subprocess.run(
        f'"{python_exe}" -m PC.layout --preset-default --copy "{out_dir}" -v',
        shell=True, env=env, cwd=str(CPYTHON_SRC), check=True,
    )

    print(f"[cpython] Build complete ({toolchain}/arm64, PGO={pgo}). Install: {out_dir}")


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

def _get_python_exe(toolchain, pgo=False):
    """Locate the built python.exe for the given config."""
    out_dir = _output_dir(toolchain, pgo)

    # Prefer the PC.layout installation
    p = out_dir / "python.exe"
    if p.exists():
        return p

    # Fallback: look in PCbuild/<platform>
    pinfo = config.platform_info()
    p = CPYTHON_SRC / "PCbuild" / pinfo["pcbuild"] / "python.exe"
    if p.exists():
        return p
    return None


# ---------------------------------------------------------------------------
# Benchmark: pyperformance
# ---------------------------------------------------------------------------

# CPU-bound subset: benchmarks most sensitive to compiler codegen differences.
# These exercise tight loops, arithmetic, object allocation, and call overhead
# rather than I/O, regex, or templating — so differences reflect compiler quality.
FAST_BENCHMARKS = [
    "deltablue",         # constraint solver — tight OOP dispatch
    "richards",          # OS simulation — method calls + branching
    "nbody",             # float arithmetic in tight loop
    "spectral_norm",     # nested float loops
    "fannkuch",          # integer permutation — branch-heavy
    "chaos",             # float geometry — math-heavy
    "float",             # basic float ops
    "pidigits",          # bignum arithmetic
    "hexiom",            # recursive search + heuristics
    "go",                # board game AI — deep branching
    "raytrace",          # 3D math — float + object overhead
    "crypto_pyaes",      # byte-level AES — integer + indexing
    "pyflate",           # zlib-like — bitwise ops
    "pickle_pure_python",  # object serialization — call overhead
    "unpickle_pure_python",
]


@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "pgo": "Use PGO build (default: False)",
        "fast": "Run only CPU-bound subset (~18 benchmarks) instead of all 112",
    },
)
def bench(c, toolchain="msvc", pgo=False, fast=False):
    """Run pyperformance benchmarks against the built CPython."""
    python_exe = _get_python_exe(toolchain, pgo)
    if not python_exe:
        suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"
        print(f"[cpython] python.exe not found for {suffix}. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"
    result_file = RESULTS_DIR / f"pyperformance_{suffix}.json"

    print(f"[cpython] Running pyperformance ({suffix})...")
    config.set_bench_priority()
    cmd = [
        "pyperformance", "run",
        f"--python={python_exe}",
        "--rigorous",
        f"--output={result_file}",
    ]
    if fast:
        cmd.extend(["--benchmarks", ",".join(FAST_BENCHMARKS)])
        print(f"[cpython] Fast mode: {len(FAST_BENCHMARKS)} CPU-bound benchmarks")
    subprocess.run(cmd, check=True)
    print(f"[cpython] pyperformance complete. Results: {result_file}")


# ---------------------------------------------------------------------------
# Benchmark: pybench
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "pgo": "Use PGO build (default: False)",
    },
)
def bench_pybench(c, toolchain="msvc", pgo=False):
    """Run pybench against the built CPython."""
    python_exe = _get_python_exe(toolchain, pgo)
    if not python_exe:
        suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"
        print(f"[cpython] python.exe not found for {suffix}. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"

    # pybench.py is shipped with CPython in Tools/pybench/
    pybench_script = CPYTHON_SRC / "Tools" / "pybench" / "pybench.py"
    if not pybench_script.exists():
        # Older location
        pybench_script = CPYTHON_SRC / "Lib" / "test" / "pybench" / "pybench.py"

    if not pybench_script.exists():
        print("[cpython] pybench.py not found in CPython source tree.")
        print("[cpython] pybench was removed in CPython 3.13+; using pyperformance instead.")
        return

    result_file = RESULTS_DIR / f"pybench_{suffix}.txt"
    config.set_bench_priority()
    subprocess.run(
        [str(python_exe), str(pybench_script), "-f", str(result_file)],
        check=True,
    )
    print(f"[cpython] pybench complete. Results: {result_file}")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "pgo": "Use PGO build (default: False)",
        "benchmark": "Specific pyperformance benchmark to profile (default: asyncio_websockets)",
    },
)
def profile(c, toolchain="msvc", pgo=False, benchmark="asyncio_websockets"):
    """Capture an ETW trace of a specific pyperformance benchmark."""
    python_exe = _get_python_exe(toolchain, pgo)
    if not python_exe:
        suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"
        print(f"[cpython] python.exe not found for {suffix}. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{toolchain}_arm64_pgo" if pgo else f"{toolchain}_arm64"
    etl_file = RESULTS_DIR / f"cpython_{suffix}_{benchmark}.etl"

    env = get_toolchain_env(toolchain)

    # Run a single benchmark under ETW tracing
    cmd = (
        f'pyperformance run '
        f'--python="{python_exe}" '
        f'--benchmarks={benchmark} '
        f'--output="{RESULTS_DIR / f"profile_{suffix}_{benchmark}.json"}"'
    )
    profile_command(cmd, output_etl=etl_file, env=env)
    print(f"[cpython] Profile saved: {etl_file}")
