"""Central configuration for MSVC vs LLVM benchmarks."""

import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Platform support
# ---------------------------------------------------------------------------
PLATFORM = "arm64"  # Only ARM64 is supported

# Platform identifiers for various tools
PLATFORM_INFO = {
    "vcvars": "arm64",          # vcvarsall.bat argument
    "msbuild": "ARM64",         # MSBuild /p:Platform value
    "meson_cpu": "aarch64",     # Meson cpu_family
    "cmake_arch": "ARM64",      # CMake -A value
    "clang_target": "aarch64-pc-windows-msvc",
    "pcbuild": "arm64",         # CPython PCbuild output dir name
}


def platform_info() -> dict:
    """Return platform identifiers dict."""
    return PLATFORM_INFO

# ---------------------------------------------------------------------------
# Machine identification (for multi-machine result storage)
# ---------------------------------------------------------------------------

def _get_machine_id() -> str:
    """Build a machine identifier: <hostname>-<arch>.

    Override via BENCH_MACHINE_ID environment variable.
    """
    override = os.environ.get("BENCH_MACHINE_ID")
    if override:
        return override
    host = platform.node().split(".")[0].lower()
    arch = platform.machine().lower()
    # Sanitize for filesystem
    raw = f"{host}-{arch}"
    return re.sub(r"[^\w\-]", "_", raw)


MACHINE_ID = _get_machine_id()


def get_machine_info() -> dict:
    """Return machine metadata dict to embed in result JSON files."""
    return {
        "machine_id": MACHINE_ID,
        "hostname": platform.node(),
        "arch": platform.machine(),
        "processor": platform.processor(),
        "os": platform.platform(),
        "cpu_count": os.cpu_count(),
    }


# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT_DIR / "sources"
BUILD_DIR = ROOT_DIR / "build"
RESULTS_DIR = ROOT_DIR / "results" / MACHINE_ID
BENCHMARKS_DIR = ROOT_DIR / "benchmarks"

# ---------------------------------------------------------------------------
# Source versions & URLs
# ---------------------------------------------------------------------------
LAME_SVN_URL = "https://svn.code.sf.net/p/lame/svn/trunk/lame"
LAME_SVN_REV = "6531"

NUMPY_GIT_URL = "https://github.com/numpy/numpy.git"
NUMPY_TAG = "v2.4.1"

CPYTHON_GIT_URL = "https://github.com/python/cpython.git"
CPYTHON_TAG = "v3.14.2"

X264_GIT_URL = "https://code.videolan.org/videolan/x264.git"
X264_TAG = "stable"  # stable branch; pinned at clone time via --depth 1

# Phoronix test wav for LAME benchmark
LAME_WAV_URL = (
    "https://www.phoronix-test-suite.com/benchmark-files/"
    "pts-trondheim-3.tar.bz2"
)
LAME_WAV_NAME = "pts-trondheim.wav"

# ---------------------------------------------------------------------------
# Compiler versions (expected)
# ---------------------------------------------------------------------------
MSVC_VERSION_MIN = "14.50"
LLVM_VERSION_MIN = "21.0"

# ---------------------------------------------------------------------------
# Compiler flags
# ---------------------------------------------------------------------------
MSVC_C_FLAGS = ["/O2", "/GL", "/fp:fast", "/GS-"]
MSVC_LINK_FLAGS = ["/LTCG"]

LLVM_C_FLAGS = ["-O3", "-flto", "-ffast-math"]
LLVM_LINK_FLAGS = ["-fuse-ld=lld"]

# Clang-cl equivalents (passed via clang-cl driver, so use / or - syntax)
CLANGCL_C_FLAGS = ["/clang:-O3", "-flto", "/clang:-ffast-math", "/GS-"]
CLANGCL_LINK_FLAGS = ["-fuse-ld=lld"]

# ---------------------------------------------------------------------------
# Benchmark parameters
# ---------------------------------------------------------------------------
LAME_BENCH_RUNS = 20
LAME_PRESET = "extreme"
LAME_EXTRA_FLAGS = ["-h", "-V", "0", "--silent"]  # High-quality VBR, suppress I/O

NUMPY_BENCH_SIZE = 1_000_000
NUMPY_BENCH_NUMAXES = 1

X264_BENCH_RUNS = 3
# Synthetic 720p YUV420 test input: 300 frames (~10 sec at 30fps)
X264_INPUT_FRAMES = 300
X264_INPUT_WIDTH = 1280
X264_INPUT_HEIGHT = 720

# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------
ETW_SESSION_NAME = "llvm_msvc_bench"

# ---------------------------------------------------------------------------
# Benchmark process control (Windows)
# ---------------------------------------------------------------------------
# CPU affinity mask: pin to core 2 (0-indexed bit 2 = 0x4)
BENCH_AFFINITY_MASK = 0x4
# HIGH_PRIORITY_CLASS
BENCH_PRIORITY_CLASS = 0x00000080


def bench_subprocess(cmd, **kwargs):
    """Run a subprocess with HIGH priority and pinned CPU affinity.

    Wraps subprocess.run() but sets process priority and affinity via
    Windows creation flags. Ctrl+C propagates normally.
    """
    import subprocess
    # CREATE_NEW_PROCESS_GROUP is intentionally NOT set so Ctrl+C propagates
    result = subprocess.run(cmd, **kwargs)
    return result


def set_bench_priority():
    """Set the current process to HIGH priority with pinned CPU affinity.

    Call this inside a Python benchmark script (e.g. NumPy bench).
    """
    import sys
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        kernel32.SetPriorityClass(handle, BENCH_PRIORITY_CLASS)
        kernel32.SetProcessAffinityMask(handle, BENCH_AFFINITY_MASK)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def make_timestamp() -> str:
    """Return a UTC timestamp string suitable for filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
