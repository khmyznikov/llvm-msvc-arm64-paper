"""Root Invoke tasks — orchestrates all benchmark subprojects."""

from invoke import Collection, task

from benchmarks.lame import tasks as lame_tasks
from benchmarks.numpy import tasks as numpy_tasks
from benchmarks.cpython import tasks as cpython_tasks
from benchmarks.strcmp import tasks as strcmp_tasks
from benchmarks.blender import tasks as blender_tasks
from benchmarks.x264 import tasks as x264_tasks


@task(
    help={"toolchain": "msvc, llvm, or both (default: both)"}
)
def fetch_all(c, toolchain="both"):
    """Fetch/checkout all project sources."""
    c.run("inv lame.fetch", pty=False)
    c.run("inv numpy.fetch", pty=False)
    c.run("inv cpython.fetch", pty=False)
    c.run("inv blender.fetch", pty=False)
    print("[all] All sources fetched.")


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
        "platform": "arm64 or x64 (default: arm64)",
    }
)
def build_all(c, toolchain="both", platform="arm64"):
    """Build all projects with the specified toolchain."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        c.run(f"inv lame.build --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv numpy.build --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv cpython.build --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv strcmp.build --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv blender.build --toolchain={tc} --platform={platform}", pty=False)
    print(f"[all] All projects built ({toolchain}/{platform}).")


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
        "platform": "arm64 or x64 (default: arm64)",
    }
)
def bench_all(c, toolchain="both", platform="arm64"):
    """Run benchmarks for all projects."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        c.run(f"inv lame.bench --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv numpy.bench --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv cpython.bench --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv strcmp.bench --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv blender.bench --toolchain={tc} --platform={platform}", pty=False)
    print(f"[all] All benchmarks complete ({toolchain}/{platform}).")


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
        "platform": "arm64 or x64 (default: arm64)",
    }
)
def profile_all(c, toolchain="both", platform="arm64"):
    """Capture ETW profiles for all projects."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        c.run(f"inv lame.profile --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv cpython.profile --toolchain={tc} --platform={platform}", pty=False)
        c.run(f"inv strcmp.profile --toolchain={tc} --platform={platform}", pty=False)
    print(f"[all] All profiles captured ({toolchain}/{platform}).")


# Build the namespace
ns = Collection()
ns.add_task(fetch_all, name="fetch-all")
ns.add_task(build_all, name="build-all")
ns.add_task(bench_all, name="bench-all")
ns.add_task(profile_all, name="profile-all")

ns.add_collection(Collection.from_module(lame_tasks), name="lame")
ns.add_collection(Collection.from_module(numpy_tasks), name="numpy")
ns.add_collection(Collection.from_module(cpython_tasks), name="cpython")
ns.add_collection(Collection.from_module(strcmp_tasks), name="strcmp")
ns.add_collection(Collection.from_module(blender_tasks), name="blender")
ns.add_collection(Collection.from_module(x264_tasks), name="x264")
