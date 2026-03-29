"""Invoke tasks for x264 H.264 encoder benchmark.

Builds x264 from source with MSVC and clang-cl (no ASM — pure C codegen
comparison), then benchmarks encoding speed on a synthetic YUV420 test input.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

from invoke import task

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common import config
from common.toolchain import get_toolchain_env, find_clangcl
from common.profiling import profile_command

X264_SRC = config.SOURCES_DIR / "x264"
BUILD_DIR = config.BUILD_DIR / "x264"
RESULTS_DIR = config.RESULTS_DIR / "x264"

# Source files are split into three groups following x264's Makefile:
# - SRCS: compiled once (shared utilities)
# - SRCS_X: compiled with -DBIT_DEPTH=8 (could also be compiled for 10-bit)
# - SRCCLI: CLI front-end (compiled once)
# Note: some .c files are #included from other .c files (unity build pattern)
#   analyse.c includes rdo.c, slicetype.c
#   rdo.c includes cavlc.c, cabac.c
# These must NOT appear in the source lists.

SRCS = [
    "common/osdep.c", "common/base.c", "common/cpu.c", "common/tables.c",
    "encoder/api.c",
]

SRCS_X = [
    "common/mc.c", "common/predict.c", "common/pixel.c",
    "common/macroblock.c", "common/frame.c", "common/dct.c",
    "common/cabac.c", "common/common.c", "common/rectangle.c",
    "common/set.c", "common/quant.c", "common/deblock.c", "common/vlc.c",
    "common/mvpred.c", "common/bitstream.c",
    "encoder/analyse.c", "encoder/me.c", "encoder/ratecontrol.c",
    "encoder/set.c", "encoder/macroblock.c",
    "encoder/cabac.c", "encoder/cavlc.c",
    # encoder/rdo.c and encoder/slicetype.c are #included from analyse.c
    "encoder/encoder.c", "encoder/lookahead.c",
    "common/win32thread.c", "common/threadpool.c",
]

SRCCLI = [
    "x264.c", "autocomplete.c", "extras/getopt.c",
    "input/input.c", "input/raw.c", "input/y4m.c",
    "input/timecode.c", "input/thread.c",
    "output/raw.c", "output/matroska.c", "output/matroska_ebml.c",
    "output/flv.c", "output/flv_bytestream.c",
    # output/mp4.c requires GPAC, output/mp4_lsmash.c requires L-SMASH — skip both
    "filters/filters.c",
    "filters/video/video.c", "filters/video/internal.c",
    "filters/video/cache.c", "filters/video/crop.c",
    "filters/video/depth.c", "filters/video/fix_vfr_pts.c",
    "filters/video/resize.c", "filters/video/select_every.c",
    "filters/video/source.c",
]


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------

@task
def fetch(c):
    """Clone x264 stable branch from VideoLAN."""
    if X264_SRC.exists():
        print(f"[x264] Source already exists at {X264_SRC}")
        return
    config.SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    c.run(
        f'git clone --depth 1 --branch {config.X264_TAG} '
        f'"{config.X264_GIT_URL}" "{X264_SRC}"'
    )
    print(f"[x264] Cloned {config.X264_TAG} to {X264_SRC}")


# ---------------------------------------------------------------------------
# Config header generation
# ---------------------------------------------------------------------------

def _write_config_headers(build_dir: Path):
    """Generate config.h and x264_config.h for a Windows build (no ASM)."""
    build_dir.mkdir(parents=True, exist_ok=True)

    # config.h — feature detection for Windows
    config_h = build_dir / "config.h"
    if not config_h.exists():
        config_h.write_text(
            '#define HAVE_MALLOC_H 0\n'
            '#define HAVE_STRING_H 1\n'
            '#define HAVE_LOG2F 1\n'
            '#define HAVE_STRTOK_R 0\n'
            '#define HAVE_CLOCK_GETTIME 0\n'
            '#define HAVE_MMAP 0\n'
            '#define HAVE_THP 0\n'
            '#define HAVE_POSIXTHREAD 0\n'
            '#define HAVE_WIN32THREAD 1\n'
            '#define HAVE_THREAD 1\n'
            '#define HAVE_OPENCL 0\n'
            '#define HAVE_VECTOREXT 0\n'
            '#define HAVE_INTERLACED 1\n'
            '#define HAVE_GPL 1\n'
            '#define HAVE_AVS 0\n'
            '#define HAVE_SWSCALE 0\n'
            '#define HAVE_LAVF 0\n'
            '#define HAVE_FFMS 0\n'
            '#define HAVE_GPAC 0\n'
            '#define HAVE_LSMASH 0\n'
            '#define HAVE_X86_INLINE_ASM 0\n'
            '#define HAVE_AS_FUNC 0\n'
            '#define HAVE_INTEL_DISPATCHER 0\n'
            '#define HAVE_MSA 0\n'
            '#define HAVE_ALTIVEC 0\n'
            '#define HAVE_ARMV6 0\n'
            '#define HAVE_ARMV6T2 0\n'
            '#define HAVE_NEON 0\n'
            '#define HAVE_AARCH64 0\n'
            '#define HAVE_LSX 0\n'
            '#define HAVE_LASX 0\n'
            '#define HAVE_MMX 0\n'
            '#define HAVE_SSE3 0\n'
            '#define HAVE_BITDEPTH8 1\n'
            '#define HAVE_BITDEPTH10 0\n'
            '#define ARCH_X86 0\n'
            '#define ARCH_X86_64 0\n'
            '#define ARCH_PPC 0\n'
            '#define ARCH_AARCH64 0\n'
            '#define ARCH_ARM 0\n'
            '#define ARCH_MIPS 0\n'
            '#define ARCH_LOONGARCH 0\n'
            '#define ARCH_UNK 1\n'
            '#define SYS_WINDOWS 1\n'
            '#define STACK_ALIGNMENT 16\n'
            '#define HAVE_CPU_COUNT 0\n'
            '#define HAVE_WINRT 0\n'
            '#define HAVE_BITDEPTH8 1\n'
            '#define HAVE_BITDEPTH10 0\n',
            encoding='utf-8'
        )

    # x264_config.h — build configuration
    x264_config_h = build_dir / "x264_config.h"
    if not x264_config_h.exists():
        # Get version info from source
        version_file = X264_SRC / "version.sh"
        api = "165"  # X264_BUILD from x264.h
        if version_file.exists():
            text = version_file.read_text()
            m = re.search(r'API="(\d+)"', text)
            if m:
                api = m.group(1)

        x264_config_h.write_text(
            '#define X264_GPL           1\n'
            '#define X264_INTERLACED    1\n'
            '#define X264_BIT_DEPTH     8\n'
            '#define X264_CHROMA_FORMAT 0\n'
            '#define X264_REV           1\n'
            '#define X264_REV_DIFF      0\n'
            f'#define X264_VERSION ""\n'
            f'#define X264_POINTVER "0.{api}.0"\n',
            encoding='utf-8'
        )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _src_paths(file_list: list[str]) -> list[str]:
    """Return quoted source file paths, filtering to those that exist."""
    return [f'"{X264_SRC / s}"' for s in file_list if (X264_SRC / s).exists()]


def _build_msvc(env, platform):
    """Build x264 with MSVC cl.exe.

    Compiles each source file to a uniquely-named .obj (prefixed by subdir)
    to avoid collisions (common/macroblock.c vs encoder/macroblock.c).
    """
    build_dir = BUILD_DIR / f"msvc_{platform}"
    _write_config_headers(build_dir)
    out_exe = build_dir / "x264.exe"

    inc = f'/I"{X264_SRC}" /I"{build_dir}" /I"{X264_SRC}/extras"'
    cflags = f'/O2 /GL /fp:fast /GS- /Zi /Zo /Oy- {inc} /DHAVE_CONFIG_H /D_WIN32 /DNDEBUG /DBIT_DEPTH=8 /DHIGH_BIT_DEPTH=0'

    all_srcs = SRCS + SRCS_X + SRCCLI
    obj_files = []
    for src in all_srcs:
        src_path = X264_SRC / src
        if not src_path.exists():
            continue
        # Unique obj name: common__macroblock.obj, encoder__macroblock.obj
        obj_name = src.replace("/", "__").replace("\\", "__").replace(".c", ".obj")
        obj_path = build_dir / obj_name
        obj_files.append(f'"{obj_path}"')
        cmd = f'cl /c {cflags} "{src_path}" /Fo:"{obj_path}"'
        subprocess.run(cmd, shell=True, env=env, check=True, cwd=str(build_dir),
                       stdout=subprocess.DEVNULL)

    # Link
    link_cmd = (
        f'link /OUT:"{out_exe}" /LTCG /OPT:REF /OPT:ICF /INCREMENTAL:NO '
        f'/DEBUG /DEBUGTYPE:FIXUP,CV shell32.lib {" ".join(obj_files)}'
    )
    subprocess.run(link_cmd, shell=True, env=env, check=True, cwd=str(build_dir))
    print(f"[x264] Built {out_exe.name} (msvc/{platform})")
    return out_exe


def _build_llvm(env, platform):
    """Build x264 with clang-cl."""
    build_dir = BUILD_DIR / f"llvm_{platform}"
    _write_config_headers(build_dir)
    out_exe = build_dir / "x264.exe"

    clangcl = find_clangcl()
    inc = f'/I"{X264_SRC}" /I"{build_dir}" /I"{X264_SRC}/extras"'
    cflags = (
        f'/clang:-O3 -flto /clang:-ffast-math /clang:-fuse-ld=lld '
        f'/GS- /Zi /Zo /Oy- {inc} /DHAVE_CONFIG_H /D_WIN32 /DNDEBUG '
        f'/DBIT_DEPTH=8 /DHIGH_BIT_DEPTH=0'
    )

    all_srcs = SRCS + SRCS_X + SRCCLI
    obj_files = []
    for src in all_srcs:
        src_path = X264_SRC / src
        if not src_path.exists():
            continue
        obj_name = src.replace("/", "__").replace("\\", "__").replace(".c", ".obj")
        obj_path = build_dir / obj_name
        obj_files.append(f'"{obj_path}"')
        cmd = f'"{clangcl}" /c {cflags} "{src_path}" /Fo:"{obj_path}"'
        subprocess.run(cmd, shell=True, env=env, check=True, cwd=str(build_dir),
                       stdout=subprocess.DEVNULL)

    # Link with lld-link
    lld_link = str(Path(clangcl).parent / "lld-link.exe")
    link_cmd = (
        f'"{lld_link}" /OUT:"{out_exe}" /OPT:REF /OPT:ICF /INCREMENTAL:NO '
        f'/DEBUG shell32.lib {" ".join(obj_files)}'
    )
    subprocess.run(link_cmd, shell=True, env=env, check=True, cwd=str(build_dir))
    print(f"[x264] Built {out_exe.name} (llvm/{platform})")
    return out_exe


@task(
    pre=[fetch],
    help={
        "toolchain": "msvc, llvm, or both (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def build(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM):
    """Build x264 encoder (pure C, no ASM)."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        env = get_toolchain_env(tc, platform)
        if tc == "msvc":
            _build_msvc(env, platform)
        else:
            _build_llvm(env, platform)


# ---------------------------------------------------------------------------
# Test input generation
# ---------------------------------------------------------------------------

def _ensure_test_input(platform) -> Path:
    """Generate a synthetic raw YUV420p test file if not present."""
    test_dir = BUILD_DIR / "testdata"
    test_dir.mkdir(parents=True, exist_ok=True)
    w, h = config.X264_INPUT_WIDTH, config.X264_INPUT_HEIGHT
    n = config.X264_INPUT_FRAMES
    yuv_file = test_dir / f"test_{w}x{h}_{n}frames.yuv"
    if yuv_file.exists():
        return yuv_file

    print(f"[x264] Generating synthetic {w}x{h} YUV420 test input ({n} frames)...")
    # Generate pseudo-random YUV420p data using Python
    # YUV420p frame = W*H (Y) + W*H/4 (U) + W*H/4 (V) = W*H*3/2
    import random
    random.seed(42)
    frame_size = w * h * 3 // 2
    # Write in chunks to avoid huge memory usage
    with open(yuv_file, 'wb') as f:
        for i in range(n):
            # Mix of flat areas and gradients for realistic encoding complexity
            frame = bytearray(frame_size)
            # Y plane: gradient + noise
            for y in range(h):
                for x in range(w):
                    base = int((x / w * 128 + y / h * 64 + i * 7) % 256)
                    noise = random.randint(-8, 8)
                    frame[y * w + x] = max(0, min(255, base + noise))
            # U/V planes: simpler pattern
            uv_offset = w * h
            for j in range(w * h // 2):
                frame[uv_offset + j] = (j * 3 + i * 11) & 0xFF
            f.write(frame)
    size_mb = yuv_file.stat().st_size / (1024 * 1024)
    print(f"[x264] Generated {yuv_file.name} ({size_mb:.1f} MB)")
    return yuv_file


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
    """Benchmark x264 encoding speed (fps) on a synthetic test input."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    yuv_file = _ensure_test_input(platform)

    w, h = config.X264_INPUT_WIDTH, config.X264_INPUT_HEIGHT
    n = config.X264_INPUT_FRAMES
    results = {}

    for tc in toolchains:
        build_dir = BUILD_DIR / f"{tc}_{platform}"
        exe = build_dir / "x264.exe"
        if not exe.exists():
            print(f"[x264] {exe} not found. Run 'inv x264.build --toolchain={tc}' first.")
            continue

        runs = []
        for run_idx in range(config.X264_BENCH_RUNS):
            out_h264 = build_dir / f"bench_run{run_idx}.h264"
            cmd = [
                str(exe),
                "--input-res", f"{w}x{h}",
                "--fps", "30",
                "--frames", str(n),
                "--preset", "medium",
                "--tune", "psnr",
                "--output", str(out_h264),
                str(yuv_file),
            ]
            print(f"  [{tc}] Run {run_idx + 1}/{config.X264_BENCH_RUNS}...", end=" ", flush=True)
            config.set_bench_priority()
            start = time.perf_counter()
            result = subprocess.run(
                cmd, capture_output=True, text=True,
            )
            elapsed = time.perf_counter() - start

            # Parse x264's output for fps
            fps = None
            stderr = result.stderr or ""
            stdout = result.stdout or ""
            output = stderr + stdout
            # x264 prints: "encoded 300 frames, 45.23 fps, 1234.56 kb/s"
            m = re.search(r'encoded\s+\d+\s+frames?,\s+([\d.]+)\s+fps', output)
            if m:
                fps = float(m.group(1))

            run_data = {
                "elapsed_sec": elapsed,
                "fps": fps,
                "returncode": result.returncode,
            }
            runs.append(run_data)
            fps_str = f"{fps:.2f} fps" if fps else f"{elapsed:.1f}s (fps not parsed)"
            print(fps_str)

            # Clean up output file
            if out_h264.exists():
                out_h264.unlink()

        fps_values = [r["fps"] for r in runs if r["fps"] is not None]
        results[tc] = {
            "runs": runs,
            "mean_fps": sum(fps_values) / len(fps_values) if fps_values else None,
            "min_fps": min(fps_values) if fps_values else None,
            "max_fps": max(fps_values) if fps_values else None,
        }
        if fps_values:
            print(f"  [{tc}] Mean: {results[tc]['mean_fps']:.2f} fps")

    result_file = RESULTS_DIR / f"x264_results_{platform}.json"
    result_json = {
        "benchmark": "x264_encode",
        "machine": config.get_machine_info(),
        "platform": platform,
        "input": {
            "width": w,
            "height": h,
            "frames": n,
            "format": "yuv420p",
            "preset": "medium",
        },
        "runs_per_toolchain": config.X264_BENCH_RUNS,
        "results": results,
    }
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(json.dumps(result_json, indent=2))
    print(f"[x264] Results: {result_file}")


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------

@task(
    help={
        "toolchain": "msvc or llvm (default: msvc)",
        "platform": f"arm64 or x64 (default: {config.DEFAULT_PLATFORM})",
    },
)
def profile(c, toolchain="msvc", platform=config.DEFAULT_PLATFORM):
    """Capture an ETW CPU sampling trace of x264 encoding."""
    build_dir = BUILD_DIR / f"{toolchain}_{platform}"
    exe = build_dir / "x264.exe"
    if not exe.exists():
        print(f"[x264] {exe} not found. Build first.")
        return

    yuv_file = _ensure_test_input(platform)
    w, h = config.X264_INPUT_WIDTH, config.X264_INPUT_HEIGHT
    n = config.X264_INPUT_FRAMES
    out_h264 = build_dir / "profile_output.h264"

    cmd = [
        str(exe),
        "--input-res", f"{w}x{h}",
        "--fps", "30",
        "--frames", str(n),
        "--preset", "medium",
        "--tune", "psnr",
        "--output", str(out_h264),
        str(yuv_file),
    ]
    trace_file = RESULTS_DIR / f"xperf_x264_{toolchain}_{platform}.etl"
    profile_command(cmd, trace_file, f"x264 ({toolchain})")
