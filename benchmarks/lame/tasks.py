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
BUILD_LOGS_DIR = config.ROOT_DIR / "build-logs" / "lame"
PATCHES_DIR = Path(__file__).resolve().parent / "patches"
OVERRIDE_PROPS = Path(__file__).resolve().parent / "vs2019_override.props"


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

    # Ensure svn is on PATH (SlikSvn default location)
    svn_path = shutil.which("svn")
    if not svn_path:
        slik = Path(r"C:\Program Files\SlikSvn\bin")
        if (slik / "svn.exe").exists():
            os.environ["PATH"] = str(slik) + ";" + os.environ.get("PATH", "")

    c.run(
        f'svn checkout -r {config.LAME_SVN_REV} '
        f'"{config.LAME_SVN_URL}" "{LAME_SRC}"'
    )
    print(f"[lame] Checked out r{config.LAME_SVN_REV} to {LAME_SRC}")


@task(pre=[fetch])
def patch(c):
    """Apply configMS.h stdint fix (required for clang-cl)."""
    marker = LAME_SRC / ".patched_base"
    if marker.exists():
        print("[lame] Already patched (base).")
        return

    # Fix configMS.h: replace manual typedefs with #include <stdint.h>
    config_ms = LAME_SRC / "configMS.h"
    if config_ms.exists():
        text = config_ms.read_text(encoding="utf-8")
        old_block = 'typedef __int8 int8_t;'
        if old_block in text:
            lines = text.splitlines(keepends=True)
            new_lines = []
            inserted = False
            for line in lines:
                stripped = line.strip()
                if 'typedef __int' in stripped and '_t;' in stripped:
                    if not inserted:
                        new_lines.append('#include <stdint.h>\n')
                        inserted = True
                    continue
                elif 'typedef unsigned __int' in stripped and '_t;' in stripped:
                    continue
                else:
                    new_lines.append(line)
            config_ms.write_text(''.join(new_lines), encoding="utf-8")
            print("[lame] Patched configMS.h: replaced typedefs with #include <stdint.h>")

    marker.write_text("patched")
    print("[lame] Base patches applied.")


@task(pre=[patch])
def patch_arm64(c):
    """Add ARM64 platform to VS2019 solution (only needed for --platform=arm64)."""
    marker = LAME_SRC / ".patched_arm64"
    if marker.exists():
        print("[lame] ARM64 platform already added.")
        return

    _patch_sln_for_arm64()
    _patch_vcxprojs_for_arm64()

    marker.write_text("patched")
    print("[lame] ARM64 platform patches applied.")


def _patch_vcxprojs_for_arm64():
    """Add ARM64 configurations to .vcxproj files using XML parsing."""
    import xml.etree.ElementTree as ET

    vcxproj_dir = LAME_SRC / "vc_solution"
    ns = "http://schemas.microsoft.com/developer/msbuild/2003"
    ET.register_namespace("", ns)

    for vcxproj_path in vcxproj_dir.rglob("*.vcxproj"):
        tree = ET.parse(str(vcxproj_path))
        root = tree.getroot()

        # Check if ARM64 already present
        if any("ARM64" in (el.get("Include", "") + el.get("Condition", ""))
               for el in root.iter()):
            continue

        # 1. Add ARM64 to ProjectConfiguration ItemGroup
        for item_group in root.findall(f"{{{ns}}}ItemGroup"):
            configs = item_group.findall(f"{{{ns}}}ProjectConfiguration")
            if not configs:
                continue
            # Find Release|x64 config
            for cfg in configs:
                include = cfg.get("Include", "")
                if include == "Release|x64":
                    # Clone it for ARM64
                    arm64_cfg = ET.SubElement(item_group, f"{{{ns}}}ProjectConfiguration")
                    arm64_cfg.set("Include", "Release|ARM64")
                    cfg_el = ET.SubElement(arm64_cfg, f"{{{ns}}}Configuration")
                    cfg_el.text = "Release"
                    plat_el = ET.SubElement(arm64_cfg, f"{{{ns}}}Platform")
                    plat_el.text = "ARM64"
                    break

        # 2. Clone Release|x64 conditioned elements for ARM64
        elements_to_add = []
        for elem in list(root):
            condition = elem.get("Condition", "")
            if "'Release|x64'" in condition:
                import copy
                arm64_elem = copy.deepcopy(elem)
                arm64_condition = condition.replace("x64", "ARM64")
                arm64_elem.set("Condition", arm64_condition)
                # Remove NASM/SSE-specific child elements
                for child in list(arm64_elem):
                    child_text = ET.tostring(child, encoding="unicode")
                    if any(kw in child_text for kw in ["NASM", "nasm", "SSE2", "__SSE__", ".nas"]):
                        arm64_elem.remove(child)
                    # Also clean sub-children
                    for subchild in list(child):
                        sub_text = ET.tostring(subchild, encoding="unicode")
                        if any(kw in sub_text for kw in ["NASM", "nasm", "SSE2", "__SSE__", ".nas"]):
                            child.remove(subchild)
                elements_to_add.append((elem, arm64_elem))

        for after_elem, new_elem in elements_to_add:
            idx = list(root).index(after_elem)
            root.insert(idx + 1, new_elem)

        # Write back with XML declaration
        tree.write(str(vcxproj_path), xml_declaration=True, encoding="utf-8")

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
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def build(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM):
    """Build LAME with the specified toolchain and platform."""
    # ARM64 needs extra patching (x64 configs already exist in the VS2019 solution)
    if platform == "arm64":
        patch_arm64(c)

    pinfo = config.platform_info(platform)
    env = get_toolchain_env(toolchain, platform)
    msbuild = find_msbuild(env)

    out_dir = BENCH_DIR / f"{toolchain}_{platform}"
    out_dir.mkdir(parents=True, exist_ok=True)

    override_prop = str(OVERRIDE_PROPS).replace("\\", "/")
    if toolchain == "llvm":
        clangcl = find_clangcl()
        llvm_dir = str(clangcl.parent.parent)  # e.g. C:\Program Files\LLVM
        # Auto-detect LLVM tools version from lib/clang/<ver>
        llvm_tools_ver = ""
        lib_clang = Path(llvm_dir) / "lib" / "clang"
        if lib_clang.exists():
            versions = sorted(lib_clang.iterdir(), reverse=True)
            if versions:
                llvm_tools_ver = versions[0].name
        toolset_arg = (
            f'/p:PlatformToolset=ClangCL '
            f'/p:LLVMInstallDir="{llvm_dir}" '
            f'/p:LLVMToolsVersion={llvm_tools_ver}'
        )
    else:
        # Retarget from VS2019 (v142) to current VS toolset
        toolset_arg = '/p:PlatformToolset=v143'

    cmd = (
        f'"{msbuild}" "{LAME_SLN}" '
        f'/t:lame '
        f'/p:Configuration=Release /p:Platform={pinfo["msbuild"]} '
        f'{toolset_arg} '
        f'/p:ForceImportBeforeCppTargets="{override_prop}" '
        f'/p:OutDir="{out_dir}\\\\" '
        f'/m /v:minimal'
    )

    # Capture build log
    BUILD_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = config.make_timestamp()
    log_file = BUILD_LOGS_DIR / f"{toolchain}_{platform}-build-{ts}.txt"

    result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
    log_file.write_text(
        f"Command: {cmd}\nExit code: {result.returncode}\n\n"
        f"=== STDOUT ===\n{result.stdout}\n=== STDERR ===\n{result.stderr}",
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"[lame] Build failed! See: {log_file}")
        print(result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr)
        raise SystemExit(1)

    # Copy PDB for profiling/debugging
    lame_pdb = out_dir / "lame.pdb"
    if not lame_pdb.exists():
        for pdb in out_dir.glob("*.pdb"):
            break  # at least one PDB present

    print(f"[lame] Build complete ({toolchain}/{platform}). Output: {out_dir}")


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def _ensure_wav():
    """Ensure a test WAV file exists for benchmarking.

    Generates a ~60s stereo 44.1kHz 16-bit WAV with pseudo-random noise
    if no WAV file is present. This gives a reproducible, non-trivial
    encoding workload without depending on external downloads.
    """
    wav_dir = config.SOURCES_DIR / "lame_testdata"
    wav_file = wav_dir / config.LAME_WAV_NAME
    if wav_file.exists():
        return wav_file

    wav_dir.mkdir(parents=True, exist_ok=True)

    import struct
    import wave
    import random

    print("[lame] Generating test WAV file (~60s stereo 44.1kHz 16-bit)...")
    sample_rate = 44100
    channels = 2
    duration_sec = 60
    num_samples = sample_rate * duration_sec

    rng = random.Random(42)  # deterministic for reproducibility
    with wave.open(str(wav_file), "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # Write in chunks to avoid huge memory use
        chunk = 44100  # 1 second at a time
        for offset in range(0, num_samples, chunk):
            n = min(chunk, num_samples - offset)
            frames = bytearray(n * channels * 2)
            for i in range(0, len(frames), 2):
                # 16-bit signed samples covering full range
                sample = rng.randint(-32768, 32767)
                struct.pack_into("<h", frames, i, sample)
            wf.writeframes(frames)

    size_mb = wav_file.stat().st_size / (1024 * 1024)
    print(f"[lame] Generated {wav_file.name} ({size_mb:.1f} MB)")
    return wav_file


@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
        "runs": f"Number of runs (default: {config.LAME_BENCH_RUNS})",
    },
)
def bench(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM, runs=config.LAME_BENCH_RUNS):
    """Benchmark LAME encoding: pts-trondheim.wav to MP3, --preset extreme."""
    out_dir = BENCH_DIR / f"{toolchain}_{platform}"
    lame_exe = out_dir / "lame.exe"
    if not lame_exe.exists():
        print(f"[lame] {lame_exe} not found. Run 'inv lame.build --toolchain={toolchain} --platform={platform}' first.")
        return

    wav_file = _ensure_wav()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    encode_args = (
        f'"{lame_exe}" {" ".join(config.LAME_EXTRA_FLAGS)} '
        f'--preset {config.LAME_PRESET} "{wav_file}"'
    )

    # Warmup run (prime disk cache, DLL loads)
    warmup_mp3 = out_dir / "bench_warmup.mp3"
    subprocess.run(
        f'{encode_args} "{warmup_mp3}"',
        shell=True, check=True, capture_output=True,
    )
    warmup_mp3.unlink(missing_ok=True)

    results = []
    for i in range(1, runs + 1):
        out_mp3 = out_dir / f"bench_output_{i}.mp3"
        bench_cmd = f'{config.START_TEMPLATE} {encode_args} "{out_mp3}"'
        start = time.perf_counter()
        subprocess.run(bench_cmd, shell=True, check=True, capture_output=True)
        elapsed = time.perf_counter() - start
        results.append(elapsed)
        out_mp3.unlink(missing_ok=True)
        print(f"  Run {i}/{runs}: {elapsed:.3f}s")

    result_file = RESULTS_DIR / f"lame_{toolchain}_{platform}.json"
    result_data = {
        "benchmark": "lame_mp3",
        "toolchain": toolchain,
        "platform": platform,
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
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def profile(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM):
    """Capture an ETW CPU sampling trace of a LAME encoding run."""
    out_dir = BENCH_DIR / f"{toolchain}_{platform}"
    lame_exe = out_dir / "lame.exe"
    if not lame_exe.exists():
        print(f"[lame] {lame_exe} not found. Run 'inv lame.build --toolchain={toolchain} --platform={platform}' first.")
        return

    wav_file = _ensure_wav()
    out_mp3 = out_dir / "profile_output.mp3"
    etl_file = RESULTS_DIR / f"lame_{toolchain}_{platform}.etl"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    env = get_toolchain_env(toolchain, platform)

    lame_cmd = [
        str(lame_exe),
        *config.LAME_EXTRA_FLAGS,
        "--preset", config.LAME_PRESET,
        str(wav_file), str(out_mp3),
    ]
    profile_command(lame_cmd, output_etl=etl_file, env=env)
    if out_mp3.exists():
        out_mp3.unlink()
    print(f"[lame] Profile saved: {etl_file}")
