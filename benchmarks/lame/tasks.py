"""Invoke tasks for LAME MP3 encoder benchmark."""

import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

from invoke import task

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common import config
from common.toolchain import get_toolchain_env, find_msbuild, find_clangcl
from common.profiling import profile_command

LAME_SRC = config.SOURCES_DIR / "lame"
LAME_SLN = LAME_SRC / "vc_solution" / "vs2019_lame.sln"
BENCH_DIR = config.BUILD_DIR / "lame"
RESULTS_DIR = config.RESULTS_DIR / "lame"
PATCHES_DIR = Path(__file__).resolve().parent / "patches"
OVERRIDE_PROPS = Path(__file__).resolve().parent / "vs2019_arm64_override.props"


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------

@task
def fetch(c):
    """Checkout LAME trunk from SVN at revision r6531."""
    if LAME_SRC.exists():
        print(f"[lame] Source already exists at {LAME_SRC}")
        return
    config.SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    c.run(
        f'svn checkout -r {config.LAME_SVN_REV} '
        f'"{config.LAME_SVN_URL}" "{LAME_SRC}"'
    )
    print(f"[lame] Checked out r{config.LAME_SVN_REV} to {LAME_SRC}")


@task(pre=[fetch])
def patch(c):
    """Apply ARM64 platform patches and configMS.h stdint fix."""
    marker = LAME_SRC / ".arm64_patched"
    if marker.exists():
        print("[lame] Already patched.")
        return

    # 1. Fix configMS.h: replace manual typedefs with #include <stdint.h>
    config_ms = LAME_SRC / "configMS.h"
    if config_ms.exists():
        text = config_ms.read_text(encoding="utf-8")
        # Replace MSVC-specific manual integer typedefs
        old_block = 'typedef __int8 int8_t;'
        if old_block in text:
            # Replace the typedef block with #include <stdint.h>
            lines = text.splitlines(keepends=True)
            new_lines = []
            skip_typedefs = False
            inserted = False
            for line in lines:
                stripped = line.strip()
                if 'typedef __int' in stripped and '_t;' in stripped:
                    if not inserted:
                        new_lines.append('#include <stdint.h>\n')
                        inserted = True
                    # Skip this typedef line
                    continue
                elif 'typedef unsigned __int' in stripped and '_t;' in stripped:
                    continue  # Skip unsigned variants too
                else:
                    new_lines.append(line)
            config_ms.write_text(''.join(new_lines), encoding="utf-8")
            print("[lame] Patched configMS.h: replaced typedefs with #include <stdint.h>")

    # 2. Add ARM64 platform to .vcxproj files (inline patching)
    _patch_vcxprojs_for_arm64()

    # 3. Add ARM64 platform to .sln
    _patch_sln_for_arm64()

    marker.write_text("patched")
    print("[lame] ARM64 patches applied.")


def _patch_vcxprojs_for_arm64():
    """Add ARM64 configurations to all .vcxproj files by cloning x64 configs."""
    vcxproj_dir = LAME_SRC / "vc_solution"
    for vcxproj in vcxproj_dir.rglob("*.vcxproj"):
        text = vcxproj.read_text(encoding="utf-8")
        if "ARM64" in text:
            continue  # Already has ARM64

        import re

        # Clone x64|Release ItemDefinitionGroup for ARM64
        # Add ARM64 platform to ProjectConfiguration list
        # Add ARM64 platform to condition-based property groups

        # Step 1: Add ARM64 to ProjectConfiguration
        x64_config = (
            '    <ProjectConfiguration Include="Release|x64">\n'
            '      <Configuration>Release</Configuration>\n'
            '      <Platform>x64</Platform>\n'
            '    </ProjectConfiguration>'
        )
        arm64_config = x64_config.replace("x64", "ARM64")
        if x64_config in text:
            text = text.replace(x64_config, x64_config + "\n" + arm64_config)

        # Step 2: Clone all Release|x64 conditioned groups for ARM64
        # Replace platform conditions
        x64_blocks = re.findall(
            r"([ \t]*<[^>]+Condition=\"[^\"]*'Release\|x64'[^\"]*\"[^>]*>.*?</[^>]+>)",
            text,
            flags=re.DOTALL,
        )
        for block in x64_blocks:
            arm64_block = block.replace("x64", "ARM64")
            # Remove NASM and SSE references from ARM64 blocks
            arm64_block = re.sub(r'.*[Nn][Aa][Ss][Mm].*\n?', '', arm64_block)
            arm64_block = re.sub(r'.*SSE2.*\n?', '', arm64_block)
            arm64_block = re.sub(r'.*__SSE__.*\n?', '', arm64_block)
            text = text.replace(block, block + "\n" + arm64_block)

        vcxproj.write_text(text, encoding="utf-8")
    print("[lame] Added ARM64 platform to .vcxproj files.")


def _patch_sln_for_arm64():
    """Add ARM64 platform configurations to the VS2019 solution file."""
    sln = LAME_SLN
    if not sln.exists():
        print(f"[lame] Warning: Solution not found at {sln}")
        return
    text = sln.read_text(encoding="utf-8")
    if "ARM64" in text:
        return

    # Add ARM64 entries to GlobalSection(SolutionConfigurationPlatforms)
    text = text.replace(
        "Release|x64 = Release|x64",
        "Release|x64 = Release|x64\n\t\tRelease|ARM64 = Release|ARM64",
    )

    # For each project configuration, clone x64 -> ARM64
    import re
    # Pattern: {GUID}.Release|x64.ActiveCfg = Release|x64
    x64_lines = re.findall(r'(\t\t\{[^}]+\}\.Release\|x64\.[^\n]+)\n', text)
    for line in x64_lines:
        arm64_line = line.replace("x64", "ARM64")
        text = text.replace(line, line + "\n" + arm64_line)

    sln.write_text(text, encoding="utf-8")
    print("[lame] Added ARM64 platform to solution file.")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

@task(
    pre=[patch],
    help={"toolchain": "msvc or llvm (default: msvc)"},
)
def build(c, toolchain="msvc"):
    """Build LAME for ARM64 with the specified toolchain."""
    env = get_toolchain_env(toolchain)
    msbuild = find_msbuild(env)

    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    override_prop = str(OVERRIDE_PROPS).replace("\\", "/")
    toolset_arg = ""
    if toolchain == "llvm":
        toolset_arg = '/p:PlatformToolset=ClangCL'

    cmd = (
        f'"{msbuild}" "{LAME_SLN}" '
        f'/p:Configuration=Release /p:Platform=ARM64 '
        f'{toolset_arg} '
        f'/p:ForceImportBeforeCppTargets="{override_prop}" '
        f'/p:OutDir="{BENCH_DIR / toolchain}\\\\" '
        f'/m /v:minimal'
    )
    subprocess.run(cmd, shell=True, env=env, check=True)
    print(f"[lame] Build complete ({toolchain}). Output: {BENCH_DIR / toolchain}")


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def _ensure_wav():
    """Download the Phoronix test WAV file if not present."""
    wav_dir = config.SOURCES_DIR / "lame_testdata"
    wav_file = wav_dir / config.LAME_WAV_NAME
    if wav_file.exists():
        return wav_file

    wav_dir.mkdir(parents=True, exist_ok=True)
    archive = wav_dir / "pts-trondheim-3.tar.bz2"
    if not archive.exists():
        print(f"[lame] Downloading test WAV from Phoronix...")
        urllib.request.urlretrieve(config.LAME_WAV_URL, str(archive))

    # Extract
    import bz2
    with tarfile.open(str(archive), "r:bz2") as tf:
        tf.extractall(str(wav_dir))

    # Find the wav file in extracted content
    for f in wav_dir.rglob("*.wav"):
        if "trondheim" in f.name.lower():
            if f != wav_file:
                shutil.copy2(str(f), str(wav_file))
            return wav_file

    raise FileNotFoundError(f"Could not find WAV file after extracting {archive}")


@task(
    help={"toolchain": "msvc or llvm (default: msvc)", "runs": f"Number of runs (default: {config.LAME_BENCH_RUNS})"},
)
def bench(c, toolchain="msvc", runs=config.LAME_BENCH_RUNS):
    """Benchmark LAME encoding: pts-trondheim.wav → MP3, --preset extreme."""
    lame_exe = BENCH_DIR / toolchain / "lame.exe"
    if not lame_exe.exists():
        print(f"[lame] {lame_exe} not found. Run 'inv lame.build --toolchain={toolchain}' first.")
        return

    wav_file = _ensure_wav()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for i in range(1, runs + 1):
        out_mp3 = BENCH_DIR / toolchain / f"bench_output_{i}.mp3"
        start = time.perf_counter()
        subprocess.run(
            [str(lame_exe), "--preset", config.LAME_PRESET, str(wav_file), str(out_mp3)],
            check=True,
            capture_output=True,
        )
        elapsed = time.perf_counter() - start
        results.append(elapsed)
        # Clean up output
        if out_mp3.exists():
            out_mp3.unlink()
        print(f"  Run {i}/{runs}: {elapsed:.3f}s")

    result_file = RESULTS_DIR / f"lame_{toolchain}.json"
    result_data = {
        "benchmark": "lame_mp3",
        "toolchain": toolchain,
        "runs": runs,
        "preset": config.LAME_PRESET,
        "times_sec": results,
        "mean_sec": sum(results) / len(results),
        "min_sec": min(results),
        "max_sec": max(results),
    }
    result_file.write_text(json.dumps(result_data, indent=2))
    print(f"[lame] Benchmark complete ({toolchain}). Mean: {result_data['mean_sec']:.3f}s")
    print(f"[lame] Results: {result_file}")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@task(
    help={"toolchain": "msvc or llvm (default: msvc)"},
)
def profile(c, toolchain="msvc"):
    """Capture an ETW CPU sampling trace of a LAME encoding run."""
    lame_exe = BENCH_DIR / toolchain / "lame.exe"
    if not lame_exe.exists():
        print(f"[lame] {lame_exe} not found. Run 'inv lame.build --toolchain={toolchain}' first.")
        return

    wav_file = _ensure_wav()
    out_mp3 = BENCH_DIR / toolchain / "profile_output.mp3"
    etl_file = RESULTS_DIR / f"lame_{toolchain}.etl"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    env = get_toolchain_env(toolchain)
    profile_command(
        [str(lame_exe), "--preset", config.LAME_PRESET, str(wav_file), str(out_mp3)],
        output_etl=etl_file,
        env=env,
    )
    if out_mp3.exists():
        out_mp3.unlink()
    print(f"[lame] Profile saved: {etl_file}")
