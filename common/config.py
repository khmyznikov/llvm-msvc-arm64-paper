"""Central configuration for MSVC vs LLVM ARM64 benchmarks."""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT_DIR / "sources"
BUILD_DIR = ROOT_DIR / "build"
RESULTS_DIR = ROOT_DIR / "results"
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

BLENDER_GIT_URL = "https://projects.blender.org/blender/blender.git"
BLENDER_TAG = "v5.0.1"
BLENDER_MAIN_COMMIT = "76c90257"

# Phoronix test wav for LAME benchmark
LAME_WAV_URL = (
    "https://www.phoronix-test-suite.com/benchmark-files/"
    "pts-trondheim-3.tar.bz2"
)
LAME_WAV_NAME = "pts-trondheim.wav"

# Blender benchmark scenes
BLENDER_BENCHMARKS_URL = (
    "https://projects.blender.org/blender/blender-benchmarks"
)

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

NUMPY_BENCH_SIZE = 1_000_000
NUMPY_BENCH_NUMAXES = 1

STRCMP_BENCH_RUNS = 3

BLENDER_SCENES = [
    "bmw27", "barbershop_interior", "classroom", "fishy_cat",
    "koro", "monster", "pavilion_barcelona", "pabellon_barcelona",
    "spring", "teacher", "victor", "village",
    "wasp", "junkshop",
]

# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------
ETW_SESSION_NAME = "llvm_msvc_bench"
