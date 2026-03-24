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
    """Copy profiling support files into CPython PCbuild/."""
    marker = CPYTHON_SRC / ".bench_patched"
    if marker.exists():
        print("[cpython] Already patched.")
        return

    pcbuild = CPYTHON_SRC / "PCbuild"

    # Copy msbuild.rsp for frame pointer support
    shutil.copy2(str(ASSETS_DIR / "msbuild.rsp"), str(pcbuild / "msbuild.rsp"))

    # Copy clang-cl props for frame pointer support
    shutil.copy2(
        str(ASSETS_DIR / "pyproject-clangcl.props"),
        str(pcbuild / "pyproject-clangcl.props"),
    )

    marker.write_text("patched")
    print("[cpython] Profiling patches applied to PCbuild/.")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_cmd(toolchain, pgo=False):
    """Construct the PCbuild/build.bat command."""
    build_bat = CPYTHON_SRC / "PCbuild" / "build.bat"
    cmd = f'"{build_bat}" -c Release -p ARM64'
    if pgo:
        cmd += " --pgo"
    if toolchain == "llvm":
        clangcl = find_clangcl()
        llvm_dir = clangcl.parent.parent  # e.g. C:\Program Files\LLVM
        cmd += f' "/p:PlatformToolset=ClangCL"'
        cmd += f' "/p:LLVMInstallDir={llvm_dir}"'
    return cmd


def _output_dir(toolchain, pgo=False):
    suffix = f"{toolchain}_pgo" if pgo else toolchain
    return BUILD_DIR / suffix


@task(
    pre=[patch],
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "pgo": "Enable PGO build (default: False)",
    },
)
def build(c, toolchain="msvc", pgo=False):
    """Build CPython for ARM64 with the specified toolchain."""
    env = get_toolchain_env(toolchain)
    cmd = _build_cmd(toolchain, pgo)

    print(f"[cpython] Building ({toolchain}, PGO={pgo})...")
    subprocess.run(cmd, shell=True, env=env, cwd=str(CPYTHON_SRC), check=True)

    # Copy the built python.exe path info for reference
    out_dir = _output_dir(toolchain, pgo)
    out_dir.mkdir(parents=True, exist_ok=True)

    # CPython outputs to PCbuild/arm64/
    pcbuild_out = CPYTHON_SRC / "PCbuild" / "arm64"
    python_exe = pcbuild_out / "python.exe"
    if python_exe.exists():
        # Write a pointer file so bench tasks know where the binary is
        (out_dir / "python_path.txt").write_text(str(python_exe))
        print(f"[cpython] Build complete ({toolchain}, PGO={pgo}). Binary: {python_exe}")
    else:
        print(f"[cpython] Warning: python.exe not found at {python_exe}")
        print(f"[cpython] Check PCbuild output in {pcbuild_out}")


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

def _get_python_exe(toolchain, pgo=False):
    """Locate the built python.exe for the given config."""
    out_dir = _output_dir(toolchain, pgo)
    pointer = out_dir / "python_path.txt"
    if pointer.exists():
        p = Path(pointer.read_text().strip())
        if p.exists():
            return p

    # Fallback: look in PCbuild/arm64
    p = CPYTHON_SRC / "PCbuild" / "arm64" / "python.exe"
    if p.exists():
        return p
    return None


# ---------------------------------------------------------------------------
# Benchmark: pyperformance
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "pgo": "Use PGO build (default: False)",
    },
)
def bench(c, toolchain="msvc", pgo=False):
    """Run pyperformance benchmarks against the built CPython."""
    python_exe = _get_python_exe(toolchain, pgo)
    if not python_exe:
        suffix = f"{toolchain}_pgo" if pgo else toolchain
        print(f"[cpython] python.exe not found for {suffix}. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{toolchain}_pgo" if pgo else toolchain
    result_file = RESULTS_DIR / f"pyperformance_{suffix}.json"

    print(f"[cpython] Running pyperformance ({suffix})...")
    cmd = (
        f'pyperformance run '
        f'--python="{python_exe}" '
        f'--output="{result_file}"'
    )
    subprocess.run(cmd, shell=True, check=True)
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
        suffix = f"{toolchain}_pgo" if pgo else toolchain
        print(f"[cpython] python.exe not found for {suffix}. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{toolchain}_pgo" if pgo else toolchain

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
    cmd = f'"{python_exe}" "{pybench_script}" -f "{result_file}"'
    subprocess.run(cmd, shell=True, check=True)
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
        suffix = f"{toolchain}_pgo" if pgo else toolchain
        print(f"[cpython] python.exe not found for {suffix}. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{toolchain}_pgo" if pgo else toolchain
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
