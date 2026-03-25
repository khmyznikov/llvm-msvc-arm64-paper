"""Invoke tasks for custom strcmp benchmark."""

import json
import subprocess
import time
from pathlib import Path

from invoke import task

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common import config
from common.toolchain import get_toolchain_env, find_clangcl
from common.profiling import profile_command

SRC_DIR = Path(__file__).resolve().parent
SRC_FILE = SRC_DIR / "strcmp_bench.c"
BUILD_DIR = config.BUILD_DIR / "strcmp"
RESULTS_DIR = config.RESULTS_DIR / "strcmp"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_msvc(env, platform, noinline=False):
    """Build with MSVC cl.exe."""
    suffix = f"msvc_{platform}_noinline" if noinline else f"msvc_{platform}"
    out_exe = BUILD_DIR / f"strcmp_{suffix}.exe"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    defines = "/DNOINLINE" if noinline else ""
    cmd = (
        f'cl /O2 /GL /fp:fast /GS- /Zi /Zo /Oy- {defines} '
        f'"{SRC_FILE}" /Fe:"{out_exe}" '
        f'/link /LTCG /OPT:REF /OPT:ICF /INCREMENTAL:NO /DEBUG /DEBUGTYPE:FIXUP,CV'
    )
    subprocess.run(cmd, shell=True, env=env, check=True)
    print(f"[strcmp] Built {out_exe.name}")
    return out_exe


def _build_llvm(env, platform, noinline=False):
    """Build with clang-cl."""
    suffix = f"llvm_{platform}_noinline" if noinline else f"llvm_{platform}"
    out_exe = BUILD_DIR / f"strcmp_{suffix}.exe"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    clangcl = find_clangcl()
    defines = "-DNOINLINE" if noinline else ""
    cmd = (
        f'"{clangcl}" -O3 -flto /clang:-ffast-math /GS- /Zi /Zo /Oy- {defines} '
        f'"{SRC_FILE}" -o "{out_exe}" -fuse-ld=lld '
        f'/link /LTCG /OPT:REF /OPT:ICF /INCREMENTAL:NO /DEBUG /DEBUGTYPE:FIXUP,CV'
    )
    subprocess.run(cmd, shell=True, env=env, check=True)
    print(f"[strcmp] Built {out_exe.name}")
    return out_exe


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
        "noinline": "Build noinline variant (default: False)",
    },
)
def build(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM, noinline=False):
    """Build the strcmp benchmark."""
    if toolchain == "both":
        for tc in ["msvc", "llvm"]:
            env = get_toolchain_env(tc, platform)
            if tc == "msvc":
                _build_msvc(env, platform, noinline=False)
                _build_msvc(env, platform, noinline=True)
            else:
                _build_llvm(env, platform, noinline=False)
                _build_llvm(env, platform, noinline=True)
    else:
        env = get_toolchain_env(toolchain, platform)
        if toolchain == "msvc":
            _build_msvc(env, platform, noinline=noinline)
        else:
            _build_llvm(env, platform, noinline=noinline)


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def bench(c, toolchain="both", platform=config.DEFAULT_PLATFORM):
    """Run the strcmp benchmark (all variants: inline + noinline)."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]

    results = {}
    for tc in toolchains:
        for noinline_label, suffix in [("inline", f"{tc}_{platform}"), ("noinline", f"{tc}_{platform}_noinline")]:
            exe = BUILD_DIR / f"strcmp_{suffix}.exe"
            if not exe.exists():
                print(f"[strcmp] {exe.name} not found. Run 'inv strcmp.build --toolchain={tc} --platform={platform}' first.")
                continue

            print(f"[strcmp] Running {exe.name}...")
            start = time.perf_counter()
            result = subprocess.run(
                [str(exe)],
                capture_output=True, text=True, check=True,
            )
            wall_time = time.perf_counter() - start

            key = f"{tc}_{noinline_label}"
            results[key] = {
                "exe": exe.name,
                "wall_time_sec": wall_time,
                "output": result.stdout,
            }
            print(f"  {key}: {wall_time:.1f}s total")
            print(result.stdout)

    result_file = RESULTS_DIR / f"strcmp_results_{platform}.json"
    result_data = {
        "machine": config.get_machine_info(),
        "platform": platform,
        "results": results,
    }
    result_file.write_text(json.dumps(result_data, indent=2))
    print(f"[strcmp] Results: {result_file}")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
        "noinline": "Profile noinline variant (default: False)",
    },
)
def profile(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM, noinline=False):
    """Capture an ETW trace of the strcmp benchmark."""
    suffix = f"{toolchain}_{platform}_noinline" if noinline else f"{toolchain}_{platform}"
    exe = BUILD_DIR / f"strcmp_{suffix}.exe"
    if not exe.exists():
        print(f"[strcmp] {exe.name} not found. Build first.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    etl_file = RESULTS_DIR / f"strcmp_{suffix}.etl"
    env = get_toolchain_env(toolchain, platform)

    profile_command([str(exe)], output_etl=etl_file, env=env)
    print(f"[strcmp] Profile saved: {etl_file}")
