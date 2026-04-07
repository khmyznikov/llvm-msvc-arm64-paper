"""Invoke tasks for NumPy benchmark suite (multiple operations)."""

import json
import os
import subprocess
import sys
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
    help={
        "toolchain": "msvc or llvm (default: msvc)",
    },
)
def build(c, toolchain="msvc"):
    """Build NumPy with the specified toolchain via Meson (ARM64)."""
    env = get_toolchain_env(toolchain)
    # Merge current process PATH so venv tools (python, cython) are available
    current_path = os.environ.get("PATH", "")
    env["PATH"] = env.get("PATH", "") + ";" + current_path
    build_dir = BUILD_DIR / f"{toolchain}_arm64"
    tc_prefix = "msvc" if toolchain == "msvc" else "clang"
    native_file = NATIVE_DIR / f"native-{tc_prefix}-arm64.ini"

    # Clean previous build if exists
    if build_dir.exists():
        print(f"[numpy] Removing previous build: {build_dir}")
        import shutil
        shutil.rmtree(str(build_dir))

    # NumPy ships a vendored Meson with custom modules (e.g. meson_cpu/features)
    vendored_meson = NUMPY_SRC / "vendored-meson" / "meson" / "meson.py"
    meson_cmd = f'python "{vendored_meson}"' if vendored_meson.exists() else "meson"

    # Meson setup
    setup_cmd = (
        f'{meson_cmd} setup "{build_dir}" "{NUMPY_SRC}" '
        f'--native-file "{native_file}" '
        f'--prefix "{build_dir / "install"}"'
    )
    subprocess.run(setup_cmd, shell=True, env=env, check=True)

    # Meson compile
    compile_cmd = f'{meson_cmd} compile -C "{build_dir}"'
    subprocess.run(compile_cmd, shell=True, env=env, check=True)

    # Meson install (to get a usable numpy package)
    install_cmd = f'{meson_cmd} install -C "{build_dir}"'
    subprocess.run(install_cmd, shell=True, env=env, check=True)

    print(f"[numpy] Build complete ({toolchain}/arm64). Output: {build_dir}")


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

_BENCH_SCRIPT = '''
import numpy as np
import time
import json
import sys
import os

# Set high priority and CPU affinity for reduced variance
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetCurrentProcess()
    kernel32.SetPriorityClass(handle, 0x00000080)  # HIGH_PRIORITY_CLASS
    kernel32.SetProcessAffinityMask(handle, 0x4)   # Pin to core 2

# Verify which numpy is loaded
print(f"numpy: {{np.__file__}}", file=sys.stderr)

size = {size}
runs = 50
rng = np.random.default_rng(42)

# --- Benchmark operations ---
# Each is a (name, setup_fn, bench_fn) tuple.
# setup_fn returns data dict; bench_fn(data) runs the timed operation.
# All chosen to exercise NumPy-internal C loops (ufuncs, sort, reductions),
# NOT external BLAS, so the compiler toolchain is what matters.

benchmarks = []

# 1. sqrt — vectorizable math, compiler quality matters
arr_pos = rng.uniform(0.1, 100.0, size=size).astype(np.float64)
benchmarks.append(("sqrt", arr_pos, lambda d: np.sqrt(d)))

# 2. sort — quicksort on random float64 (branch-heavy, cache-intensive)
arr_sort = rng.random(size=size).astype(np.float64)
benchmarks.append(("sort", arr_sort, lambda d: np.sort(d)))

results = {{}}

for name, data, fn in benchmarks:
    # Warmup
    for _ in range(5):
        fn(data)

    times = []
    for i in range(runs):
        t0 = time.perf_counter()
        fn(data)
        t1 = time.perf_counter()
        times.append(t1 - t0)

    results[name] = {{
        "times_sec": times,
        "mean_sec": sum(times) / len(times),
        "min_sec": min(times),
        "max_sec": max(times),
    }}
    mean_us = sum(times) / len(times) * 1e6
    min_us = min(times) * 1e6
    print(f"  {{name:20s}}  mean={{mean_us:8.1f}} us   min={{min_us:8.1f}} us", file=sys.stderr)

output = {{
    "benchmark": "numpy_suite",
    "size": size,
    "runs": runs,
    "operations": results,
}}
print(json.dumps(output))
'''


@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
    },
)
def bench(c, toolchain="msvc"):
    """Run NumPy benchmark suite (multiple operations)."""
    build_dir = BUILD_DIR / f"{toolchain}_arm64"
    install_dir = build_dir / "install"
    if not install_dir.exists():
        print(f"[numpy] Build not found. Run 'inv numpy.build --toolchain={toolchain}' first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # For benchmarking we use the current process env (venv python),
    # not the compiler toolchain env — we just need PYTHONPATH
    env = os.environ.copy()

    # Find the site-packages directory under install
    site_pkgs = None
    for sp in install_dir.rglob("numpy"):
        if sp.is_dir():
            site_pkgs = sp.parent
            break
    if site_pkgs:
        env["PYTHONPATH"] = str(site_pkgs)
    else:
        print(f"[numpy] Warning: numpy not found under {install_dir}")

    script = _BENCH_SCRIPT.format(size=config.NUMPY_BENCH_SIZE)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, check=True,
    )

    # Show which numpy was loaded + per-op stats
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"[numpy] {line}")

    # Parse JSON output from the script
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line.startswith("{"):
            data = json.loads(line)
            data["toolchain"] = toolchain
            data["platform"] = "arm64"
            data["machine"] = config.get_machine_info()
            result_file = RESULTS_DIR / f"numpy_{toolchain}_arm64.json"
            result_file.write_text(json.dumps(data, indent=2))
            # Print summary
            print(f"[numpy] Benchmark suite complete ({toolchain}):")
            for op_name, op_data in data.get("operations", {}).items():
                print(f"[numpy]   {op_name:20s}  mean={op_data['mean_sec']*1e6:8.1f} µs")
            print(f"[numpy] Results: {result_file}")
            return

    print("[numpy] Warning: Could not parse benchmark output.")
    print(result.stdout)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
    },
)
def profile(c, toolchain="msvc"):
    """Capture an ETW trace of the NumPy benchmark."""
    build_dir = BUILD_DIR / f"{toolchain}_arm64"
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
    etl_file = RESULTS_DIR / f"numpy_{toolchain}_arm64.etl"
    profile_command(
        ["python", "-c", script],
        output_etl=etl_file,
        env=env,
    )
    print(f"[numpy] Profile saved: {etl_file}")
