"""Root Invoke tasks — orchestrates all benchmark subprojects."""

from invoke import Collection, task

from benchmarks.lame import tasks as lame_tasks
from benchmarks.numpy import tasks as numpy_tasks
from benchmarks.cpython import tasks as cpython_tasks
from benchmarks.x264 import tasks as x264_tasks


@task(
    help={"toolchain": "msvc, llvm, or both (default: both)"}
)
def fetch_all(c, toolchain="both"):
    """Fetch/checkout all project sources."""
    c.run("inv lame.fetch", pty=False)
    c.run("inv numpy.fetch", pty=False)
    c.run("inv cpython.fetch", pty=False)
    c.run("inv x264.fetch", pty=False)
    print("[all] All sources fetched.")


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
    }
)
def build_all(c, toolchain="both"):
    """Build all projects with the specified toolchain."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        c.run(f"inv lame.build --toolchain={tc}", pty=False)
        c.run(f"inv numpy.build --toolchain={tc}", pty=False)
        c.run(f"inv cpython.build --toolchain={tc}", pty=False)
        c.run(f"inv x264.build --toolchain={tc}", pty=False)
    print(f"[all] All projects built ({toolchain}/arm64).")


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
    }
)
def bench_all(c, toolchain="both"):
    """Run benchmarks for all projects."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        c.run(f"inv lame.bench --toolchain={tc}", pty=False)
        c.run(f"inv numpy.bench --toolchain={tc}", pty=False)
        c.run(f"inv cpython.bench --toolchain={tc}", pty=False)
        c.run(f"inv x264.bench --toolchain={tc}", pty=False)
    print(f"[all] All benchmarks complete ({toolchain}/arm64).")


@task(
    help={
        "toolchain": "msvc, llvm, or both (default: both)",
    }
)
def profile_all(c, toolchain="both"):
    """Capture ETW profiles for all projects."""
    toolchains = ["msvc", "llvm"] if toolchain == "both" else [toolchain]
    for tc in toolchains:
        c.run(f"inv lame.profile --toolchain={tc}", pty=False)
        c.run(f"inv cpython.profile --toolchain={tc}", pty=False)
        c.run(f"inv x264.profile --toolchain={tc}", pty=False)
    print(f"[all] All profiles captured ({toolchain}/arm64).")


# Build the namespace
ns = Collection()
ns.add_task(fetch_all, name="fetch-all")
ns.add_task(build_all, name="build-all")
ns.add_task(bench_all, name="bench-all")
ns.add_task(profile_all, name="profile-all")

ns.add_collection(Collection.from_module(lame_tasks), name="lame")
ns.add_collection(Collection.from_module(numpy_tasks), name="numpy")
ns.add_collection(Collection.from_module(cpython_tasks), name="cpython")
ns.add_collection(Collection.from_module(x264_tasks), name="x264")
