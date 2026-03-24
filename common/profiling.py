"""ETW profiling helpers using xperf / Windows Performance Toolkit."""

import shutil
import subprocess
import time
from pathlib import Path

from . import config


def _find_xperf() -> str:
    """Locate xperf.exe from Windows Performance Toolkit."""
    # Common install paths
    for base in [
        r"C:\Program Files (x86)\Windows Kits\10\Windows Performance Toolkit",
        r"C:\Program Files\Windows Kits\10\Windows Performance Toolkit",
    ]:
        candidate = Path(base) / "xperf.exe"
        if candidate.exists():
            return str(candidate)
    found = shutil.which("xperf")
    if found:
        return found
    raise FileNotFoundError(
        "xperf.exe not found. Install Windows Performance Toolkit "
        "(part of Windows SDK / ADK)."
    )


def start_trace(
    session_name: str = None,
    output_etl: str | Path = None,
    stack_walk: bool = True,
):
    """Start an ETW CPU sampling trace.

    Must be run as Administrator.
    """
    session_name = session_name or config.ETW_SESSION_NAME
    xperf = _find_xperf()
    cmd = [
        xperf,
        "-on", "PROC_THREAD+LOADER+PROFILE",
    ]
    if stack_walk:
        cmd += ["-stackwalk", "Profile"]
    cmd += ["-buffersize", "1024", "-minbuffers", "256", "-maxbuffers", "256"]
    subprocess.run(cmd, check=True)
    print(f"[profiling] ETW trace started (session: {session_name})")


def stop_trace(
    output_etl: str | Path,
    session_name: str = None,
):
    """Stop the ETW trace and merge into a single .etl file."""
    session_name = session_name or config.ETW_SESSION_NAME
    output_etl = Path(output_etl)
    output_etl.parent.mkdir(parents=True, exist_ok=True)

    xperf = _find_xperf()

    # Stop kernel logger
    subprocess.run([xperf, "-stop"], check=True)

    # Merge into output ETL
    merged = output_etl.with_suffix(".etl")
    subprocess.run([xperf, "-merge", str(merged)], check=False)

    # xperf -d is the combined stop+merge shorthand
    subprocess.run(
        [xperf, "-d", str(output_etl)],
        check=False,
    )
    print(f"[profiling] Trace saved to {output_etl}")
    return output_etl


def profile_command(
    cmd: list[str] | str,
    output_etl: str | Path,
    cwd=None,
    env=None,
    session_name: str = None,
):
    """Run a command while capturing an ETW CPU sampling trace.

    Returns the subprocess.CompletedProcess for the profiled command.
    """
    session_name = session_name or config.ETW_SESSION_NAME
    output_etl = Path(output_etl)

    start_trace(session_name=session_name)
    time.sleep(0.5)  # Let the trace stabilize

    try:
        if isinstance(cmd, str):
            result = subprocess.run(
                cmd, shell=True, cwd=cwd, env=env, check=True
            )
        else:
            result = subprocess.run(cmd, cwd=cwd, env=env, check=True)
    finally:
        stop_trace(output_etl, session_name=session_name)

    return result
