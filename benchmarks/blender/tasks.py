"""Invoke tasks for Blender benchmark (preliminary)."""

import json
import subprocess
import shutil
import time
from pathlib import Path

from invoke import task

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common import config
from common.toolchain import get_toolchain_env
from common.profiling import profile_command

BLENDER_SRC = config.SOURCES_DIR / "blender"
BUILD_DIR = config.BUILD_DIR / "blender"
RESULTS_DIR = config.RESULTS_DIR / "blender"
PRESETS_DIR = Path(__file__).resolve().parent / "cmake_presets"

# Blender benchmark CLI
BENCHMARK_DIR = config.SOURCES_DIR / "blender-benchmarks"


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------

@task
def fetch(c):
    """Clone Blender from the official repo and fetch dependencies."""
    if BLENDER_SRC.exists():
        print(f"[blender] Source already exists at {BLENDER_SRC}")
    else:
        config.SOURCES_DIR.mkdir(parents=True, exist_ok=True)
        # Use GIT_LFS_SKIP_SMUDGE to avoid large LFS downloads initially
        c.run(
            f'git -c lfs.fetchexclude="*" clone --depth 1 --branch {config.BLENDER_TAG} '
            f'"{config.BLENDER_GIT_URL}" "{BLENDER_SRC}"',
            warn=True,
        )
        if not BLENDER_SRC.exists():
            # Fallback: try GitHub mirror
            print("[blender] Primary clone failed, trying GitHub mirror...")
            c.run(
                f'git clone --depth 1 --branch {config.BLENDER_TAG} '
                f'"https://github.com/blender/blender.git" "{BLENDER_SRC}"',
                warn=True,
            )
        print(f"[blender] Cloned {config.BLENDER_TAG} to {BLENDER_SRC}")

    # Copy CMake presets into source tree
    presets_dest = BLENDER_SRC / "CMakeUserPresets.json"
    if not presets_dest.exists():
        _merge_presets(presets_dest)

    # Run make update to fetch prebuilt libraries
    make_bat = BLENDER_SRC / "make.bat"
    if make_bat.exists():
        print("[blender] Running 'make update' to fetch dependencies (this may take a while)...")
        c.run(f'cd /d "{BLENDER_SRC}" && make.bat update', warn=True)


def _merge_presets(dest: Path):
    """Merge all CMake preset files into a single CMakeUserPresets.json."""
    all_configure = []
    all_build = []
    for preset_file in PRESETS_DIR.glob("*.json"):
        data = json.loads(preset_file.read_text())
        all_configure.extend(data.get("configurePresets", []))
        all_build.extend(data.get("buildPresets", []))

    merged = {
        "version": 6,
        "cmakeMinimumRequired": {"major": 3, "minor": 25, "patch": 0},
        "configurePresets": all_configure,
        "buildPresets": all_build,
    }
    dest.write_text(json.dumps(merged, indent=2))
    print(f"[blender] Wrote {dest}")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@task(
    pre=[fetch],
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def build(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM):
    """Build Blender (Release, no LTCG/LTO, no PGO)."""
    env = get_toolchain_env(toolchain, platform)
    build_dir = BUILD_DIR / f"{toolchain}_{platform}"

    preset = f"{'msvc' if toolchain == 'msvc' else 'llvm'}-{platform}-release"

    # CMake configure
    configure_cmd = (
        f'cmake --preset {preset} '
        f'-S "{BLENDER_SRC}" '
        f'-B "{build_dir}"'
    )
    subprocess.run(configure_cmd, shell=True, env=env, check=True)

    # CMake build
    build_cmd = f'cmake --build "{build_dir}" --config Release --parallel'
    subprocess.run(build_cmd, shell=True, env=env, check=True)

    print(f"[blender] Build complete ({toolchain}/{platform}). Output: {build_dir}")


def _find_blender_exe(toolchain, platform=config.DEFAULT_PLATFORM):
    """Locate the built blender.exe."""
    build_dir = BUILD_DIR / f"{toolchain}_{platform}"
    for subdir in ["bin/Release", "bin", "Release", ""]:
        candidate = build_dir / subdir / "blender.exe"
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Benchmark helper: download official benchmark scenes
# ---------------------------------------------------------------------------

def _ensure_benchmark_scenes():
    """Download Blender benchmark scenes if not present."""
    if BENCHMARK_DIR.exists() and any(BENCHMARK_DIR.iterdir()):
        return BENCHMARK_DIR
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    print("[blender] Downloading benchmark scenes...")
    # Use the Blender benchmark launcher
    # Users can also manually clone: git clone https://projects.blender.org/blender/blender-benchmarks
    try:
        subprocess.run(
            f'git clone --depth 1 "{config.BLENDER_BENCHMARKS_URL}" "{BENCHMARK_DIR}"',
            shell=True, check=True,
        )
    except subprocess.CalledProcessError:
        print("[blender] Warning: Could not clone benchmark scenes.")
        print(f"[blender] Manually clone from {config.BLENDER_BENCHMARKS_URL}")
    return BENCHMARK_DIR


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def bench(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM):
    """Run Blender benchmark on all 14 official scenes."""
    blender_exe = _find_blender_exe(toolchain, platform)
    if not blender_exe:
        print(f"[blender] blender.exe not found. Run 'inv blender.build --toolchain={toolchain} --platform={platform}' first.")
        return

    scenes_dir = _ensure_benchmark_scenes()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    for scene in config.BLENDER_SCENES:
        # Find the .blend file for this scene
        blend_file = None
        for f in scenes_dir.rglob(f"*{scene}*"):
            if f.suffix == ".blend":
                blend_file = f
                break

        if not blend_file:
            print(f"  [blender] Scene '{scene}' not found, skipping.")
            continue

        print(f"  [blender] Rendering scene: {scene}...")
        start = time.perf_counter()
        result = subprocess.run(
            [
                str(blender_exe),
                "--background",
                str(blend_file),
                "--render-output", str(BUILD_DIR / f"{toolchain}_{platform}" / f"render_{scene}_"),
                "--render-frame", "1",
            ],
            capture_output=True, text=True,
        )
        elapsed = time.perf_counter() - start

        results[scene] = {
            "time_sec": elapsed,
            "returncode": result.returncode,
        }
        print(f"  {scene}: {elapsed:.1f}s")

    result_file = RESULTS_DIR / f"blender_{toolchain}_{platform}.json"
    result_data = {
        "benchmark": "blender_render",
        "machine": config.get_machine_info(),
        "toolchain": toolchain,
        "platform": platform,
        "scenes": results,
    }
    result_file.write_text(json.dumps(result_data, indent=2))
    print(f"[blender] Benchmark complete ({toolchain}). Results: {result_file}")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
        "scene": "Scene to profile (default: bmw27)",
    },
)
def profile(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM, scene="bmw27"):
    """Capture an ETW trace of a Blender render."""
    blender_exe = _find_blender_exe(toolchain, platform)
    if not blender_exe:
        print(f"[blender] blender.exe not found. Build first.")
        return

    scenes_dir = _ensure_benchmark_scenes()
    blend_file = None
    for f in scenes_dir.rglob(f"*{scene}*"):
        if f.suffix == ".blend":
            blend_file = f
            break

    if not blend_file:
        print(f"[blender] Scene '{scene}' not found in benchmark scenes.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    etl_file = RESULTS_DIR / f"blender_{toolchain}_{platform}_{scene}.etl"
    env = get_toolchain_env(toolchain, platform)

    profile_command(
        [
            str(blender_exe),
            "--background",
            str(blend_file),
            "--render-output", str(BUILD_DIR / f"{toolchain}_{platform}" / f"profile_{scene}_"),
            "--render-frame", "1",
        ],
        output_etl=etl_file,
        env=env,
    )
    print(f"[blender] Profile saved: {etl_file}")
