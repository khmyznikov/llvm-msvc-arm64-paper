"""Invoke tasks for NumPy count_nonzero benchmark."""

import json
import subprocess
import time
from pathlib import Path

from invoke import task

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common import config
from common.toolchain import get_toolchain_env
from common.profiling import profile_command

NUMPY_SRC = config.SOURCES_DIR / "numpy"
BUILD_DIR = config.BUILD_DIR / "numpy"
RESULTS_DIR = config.RESULTS_DIR / "numpy"
NATIVE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------

@task
def fetch(c):
    """Clone NumPy from GitHub at tag v2.4.1."""
    if NUMPY_SRC.exists():
        print(f"[numpy] Source already exists at {NUMPY_SRC}")
        return
    config.SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    c.run(
        f'git clone --depth 1 --branch {config.NUMPY_TAG} '
        f'"{config.NUMPY_GIT_URL}" "{NUMPY_SRC}"'
    )
    # Initialize submodules (numpy has vendored meson, etc.)
    c.run(f'git -C "{NUMPY_SRC}" submodule update --init --recursive')
    print(f"[numpy] Cloned {config.NUMPY_TAG} to {NUMPY_SRC}")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@task(
    pre=[fetch],
    help={"toolchain": "msvc or llvm (default: msvc)"},
)
def build(c, toolchain="msvc"):
    """Build NumPy for ARM64 with the specified toolchain via Meson."""
    env = get_toolchain_env(toolchain)
    build_dir = BUILD_DIR / toolchain
    native_file = NATIVE_DIR / f"native-{'msvc' if toolchain == 'msvc' else 'clang'}-arm64.ini"

    # Clean previous build if exists
    if build_dir.exists():
        print(f"[numpy] Removing previous build: {build_dir}")
        import shutil
        shutil.rmtree(str(build_dir))

    # Meson setup
    setup_cmd = (
        f'meson setup "{build_dir}" "{NUMPY_SRC}" '
        f'--native-file "{native_file}" '
        f'--prefix "{build_dir / "install"}"'
    )
    subprocess.run(setup_cmd, shell=True, env=env, check=True)

    # Meson compile
    compile_cmd = f'meson compile -C "{build_dir}"'
    subprocess.run(compile_cmd, shell=True, env=env, check=True)

    # Meson install (to get a usable numpy package)
    install_cmd = f'meson install -C "{build_dir}"'
    subprocess.run(install_cmd, shell=True, env=env, check=True)

    print(f"[numpy] Build complete ({toolchain}). Output: {build_dir}")


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

_BENCH_SCRIPT = '''
import numpy as np
import time
import json
import sys

size = {size}
runs = 50
rng = np.random.default_rng(42)
arr = rng.integers(0, 10, size=size, dtype=np.int64)

# Warmup
for _ in range(5):
    np.count_nonzero(arr)

times = []
for i in range(runs):
    t0 = time.perf_counter()
    np.count_nonzero(arr)
    t1 = time.perf_counter()
    times.append(t1 - t0)

result = {{
    "benchmark": "numpy_count_nonzero",
    "size": size,
    "runs": runs,
    "times_sec": times,
    "mean_sec": sum(times) / len(times),
    "min_sec": min(times),
    "max_sec": max(times),
}}
print(json.dumps(result))
'''


@task(
    help={"toolchain": "msvc or llvm (default: msvc)"},
)
def bench(c, toolchain="msvc"):
    """Run NumPy count_nonzero benchmark."""
    build_dir = BUILD_DIR / toolchain
    install_dir = build_dir / "install"
    if not install_dir.exists():
        print(f"[numpy] Build not found. Run 'inv numpy.build --toolchain={toolchain}' first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    env = get_toolchain_env(toolchain)

    # Add the built numpy to PYTHONPATH
    # Find the site-packages directory under install
    site_pkgs = None
    for sp in install_dir.rglob("numpy"):
        if sp.is_dir():
            site_pkgs = sp.parent
            break
    if site_pkgs:
        env["PYTHONPATH"] = str(site_pkgs)

    script = _BENCH_SCRIPT.format(size=config.NUMPY_BENCH_SIZE)
    result = subprocess.run(
        ["python", "-c", script],
        capture_output=True, text=True, env=env, check=True,
    )

    # Parse JSON output from the script
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line.startswith("{"):
            data = json.loads(line)
            data["toolchain"] = toolchain
            result_file = RESULTS_DIR / f"numpy_{toolchain}.json"
            result_file.write_text(json.dumps(data, indent=2))
            print(f"[numpy] Benchmark complete ({toolchain}). Mean: {data['mean_sec']*1e6:.1f}µs")
            print(f"[numpy] Results: {result_file}")
            return

    print("[numpy] Warning: Could not parse benchmark output.")
    print(result.stdout)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@task(
    help={"toolchain": "msvc or llvm (default: msvc)"},
)
def profile(c, toolchain="msvc"):
    """Capture an ETW trace of the NumPy benchmark."""
    build_dir = BUILD_DIR / toolchain
    install_dir = build_dir / "install"
    if not install_dir.exists():
        print(f"[numpy] Build not found. Run 'inv numpy.build --toolchain={toolchain}' first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    env = get_toolchain_env(toolchain)

    site_pkgs = None
    for sp in install_dir.rglob("numpy"):
        if sp.is_dir():
            site_pkgs = sp.parent
            break
    if site_pkgs:
        env["PYTHONPATH"] = str(site_pkgs)

    script = _BENCH_SCRIPT.format(size=config.NUMPY_BENCH_SIZE)
    etl_file = RESULTS_DIR / f"numpy_{toolchain}.etl"
    profile_command(
        ["python", "-c", script],
        output_etl=etl_file,
        env=env,
    )
    print(f"[numpy] Profile saved: {etl_file}")
