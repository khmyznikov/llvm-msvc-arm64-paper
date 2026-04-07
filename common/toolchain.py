"""Toolchain detection and environment helpers for MSVC and LLVM on Windows."""

import json
import os
import shutil
import subprocess
from pathlib import Path


def _run(cmd, **kw):
    """Run a command and return stdout, raising on failure."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, **kw
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Visual Studio / MSVC
# ---------------------------------------------------------------------------

def find_vswhere() -> Path:
    """Locate vswhere.exe (ships with VS 2017+ Build Tools)."""
    program_files = os.environ.get(
        "ProgramFiles(x86)", r"C:\Program Files (x86)"
    )
    vswhere = Path(program_files) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.exists():
        return vswhere
    # Fallback: check PATH
    found = shutil.which("vswhere")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "vswhere.exe not found. Install Visual Studio Build Tools 2026 (or 2022)."
    )


def find_vs_install_path(platform: str | None = None) -> Path:
    """Return the newest VS installation path via vswhere."""
    from . import config as _cfg
    platform = platform or _cfg.DEFAULT_PLATFORM
    vswhere = find_vswhere()

    # Try with platform-specific component first
    component = (
        "Microsoft.VisualStudio.Component.VC.Tools.ARM64"
        if platform == "arm64"
        else "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
    )
    out = _run([
        str(vswhere),
        "-latest",
        "-products", "*",
        "-requires", component,
        "-property", "installationPath",
    ])
    if not out:
        raise FileNotFoundError(
            f"No Visual Studio installation with {platform} C++ tools found."
        )
    return Path(out.splitlines()[0])


def find_vcvarsall(platform: str | None = None) -> Path:
    """Return path to vcvarsall.bat."""
    vs_path = find_vs_install_path(platform)
    vcvars = vs_path / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvars.exists():
        raise FileNotFoundError(f"vcvarsall.bat not found at {vcvars}")
    return vcvars


def get_msvc_env(arch: str = "arm64") -> dict[str, str]:
    """Run vcvarsall.bat and capture the resulting environment variables.

    Args:
        arch: vcvarsall architecture argument ("arm64" or "x64").

    Returns a dict suitable for passing to subprocess.run(env=...).
    """
    platform = "arm64" if arch == "arm64" else "x64"
    vcvars = find_vcvarsall(platform)
    # Run vcvarsall then dump env as JSON via python one-liner
    cmd = (
        f'cmd /c ""{vcvars}" {arch} >nul 2>&1 && '
        f'python -c "import os,json;print(json.dumps(dict(os.environ)))""'
    )
    out = _run(cmd, shell=True)
    # Find the JSON object in the output (skip any vcvars banner lines)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError("Failed to capture MSVC environment from vcvarsall.bat")


def get_msvc_version(env: dict[str, str] | None = None) -> str:
    """Return the MSVC cl.exe version string (e.g. '14.50.35722.0')."""
    if env is None:
        env = get_msvc_env()
    result = subprocess.run(
        ["cl.exe"],
        capture_output=True, text=True, env=env,
    )
    # cl.exe prints version to stderr
    for line in result.stderr.splitlines():
        if "Compiler Version" in line or "version" in line.lower():
            # Extract version number pattern like 19.50.35722
            parts = line.split()
            for part in parts:
                if part[0:1].isdigit() and "." in part:
                    return part
    return "unknown"


# ---------------------------------------------------------------------------
# LLVM / clang-cl
# ---------------------------------------------------------------------------

def find_clangcl() -> Path:
    """Locate clang-cl.exe, preferring LLVM install path then PATH."""
    # Check common LLVM install locations
    for base in [
        os.environ.get("LLVM_PATH", ""),
        r"C:\Program Files\LLVM\bin",
        r"C:\Program Files (x86)\LLVM\bin",
    ]:
        if base:
            candidate = Path(base) / "clang-cl.exe"
            if candidate.exists():
                return candidate

    # Try VS-bundled LLVM
    try:
        vs_path = find_vs_install_path()
        # VS ships LLVM in VC\Tools\Llvm\ARM64\bin (or x64\bin)
        for sub in ["ARM64", "x64"]:
            candidate = vs_path / "VC" / "Tools" / "Llvm" / sub / "bin" / "clang-cl.exe"
            if candidate.exists():
                return candidate
    except FileNotFoundError:
        pass

    # Fallback: PATH
    found = shutil.which("clang-cl")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "clang-cl.exe not found. Install LLVM or set LLVM_PATH."
    )


def get_llvm_version() -> str:
    """Return the LLVM/clang-cl version string."""
    clangcl = find_clangcl()
    out = _run([str(clangcl), "--version"])
    for line in out.splitlines():
        if "clang version" in line.lower():
            parts = line.split()
            for i, part in enumerate(parts):
                if part.lower() == "version" and i + 1 < len(parts):
                    return parts[i + 1]
    return "unknown"


def find_lld_link() -> Path:
    """Locate lld-link.exe (LLVM linker)."""
    clangcl = find_clangcl()
    candidate = clangcl.parent / "lld-link.exe"
    if candidate.exists():
        return candidate
    found = shutil.which("lld-link")
    if found:
        return Path(found)
    raise FileNotFoundError("lld-link.exe not found alongside clang-cl.")


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

def get_toolchain_env(toolchain: str, platform: str | None = None) -> dict[str, str]:
    """Return environment dict for the given toolchain ('msvc' or 'llvm').

    For MSVC: full vcvarsall environment.
    For LLVM: vcvarsall environment + LLVM bin in PATH (clang-cl needs
              Windows SDK headers/libs from MSVC env).
    """
    from . import config as _cfg
    platform = platform or _cfg.DEFAULT_PLATFORM
    arch = _cfg.platform_info(platform)["vcvars"]
    env = get_msvc_env(arch)
    if toolchain == "llvm":
        clangcl = find_clangcl()
        llvm_bin = str(clangcl.parent)
        env["PATH"] = llvm_bin + ";" + env.get("PATH", "")
    return env


def run_in_env(cmd, toolchain: str = "msvc", platform: str | None = None, cwd=None, check=True, **kw):
    """Run a command within the appropriate toolchain environment."""
    env = get_toolchain_env(toolchain, platform)
    if isinstance(cmd, str):
        return subprocess.run(
            cmd, shell=True, env=env, cwd=cwd, check=check, **kw
        )
    return subprocess.run(cmd, env=env, cwd=cwd, check=check, **kw)


def find_msbuild(env: dict[str, str] | None = None) -> str:
    """Return path to MSBuild.exe from the VS installation."""
    try:
        vs_path = find_vs_install_path()
        msbuild = vs_path / "MSBuild" / "Current" / "Bin" / "MSBuild.exe"
        if msbuild.exists():
            return str(msbuild)
        # Try amd64 subdirectory
        msbuild = vs_path / "MSBuild" / "Current" / "Bin" / "amd64" / "MSBuild.exe"
        if msbuild.exists():
            return str(msbuild)
    except FileNotFoundError:
        pass
    # Fallback: check in the MSVC env PATH
    if env:
        for p in env.get("PATH", "").split(";"):
            candidate = Path(p) / "MSBuild.exe"
            if candidate.exists():
                return str(candidate)
    found = shutil.which("MSBuild")
    if found:
        return found
    raise FileNotFoundError("MSBuild.exe not found.")
