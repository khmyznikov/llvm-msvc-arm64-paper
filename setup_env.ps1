<#
.SYNOPSIS
    Environment setup and validation for MSVC vs LLVM benchmarks.

.DESCRIPTION
    Detects and validates required tools: Visual Studio 2022/2026 with x64 and ARM64 C++ tools,
    LLVM/clang-cl, Python, Git, SVN, Meson, Ninja, CMake, and Windows Performance Toolkit.
    Optionally installs missing tools via winget with the -Install switch.

.PARAMETER Install
    Attempt to install missing tools via winget.

.EXAMPLE
    .\setup_env.ps1
    .\setup_env.ps1 -Install
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Install
)

$ErrorActionPreference = "Continue"
$script:allGood = $true

function Write-Status($name, $status, $detail) {
    if ($status -eq "OK") {
        Write-Host "  [OK]   " -ForegroundColor Green -NoNewline
    } elseif ($status -eq "WARN") {
        Write-Host "  [WARN] " -ForegroundColor Yellow -NoNewline
        $script:allGood = $false
    } else {
        Write-Host "  [MISS] " -ForegroundColor Red -NoNewline
        $script:allGood = $false
    }
    Write-Host "$name" -NoNewline
    if ($detail) { Write-Host " - $detail" -ForegroundColor DarkGray } else { Write-Host "" }
}

function Test-Command($cmd) {
    try { Get-Command $cmd -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

function Install-IfMissing($name, $wingetId, $present) {
    if ($present) { return }
    if (-not $Install) {
        Write-Host "         -> Install with: winget install $wingetId" -ForegroundColor DarkYellow
        return
    }
    Write-Host "         -> Installing $name via winget..." -ForegroundColor Cyan
    winget install --id $wingetId --architecture $hostArch --accept-source-agreements --accept-package-agreements
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " MSVC vs LLVM Benchmark - Env Check"
Write-Host "=============================================" -ForegroundColor Cyan

# Target platform: ARM64 only
$hostArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLower()
$primaryPlatform = "arm64"
$primaryComponent = "Microsoft.VisualStudio.Component.VC.Tools.ARM64"
$primaryVcvarsArg = "arm64"
Write-Host " Host: $hostArch  |  Target: ARM64"
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------
# 1. Visual Studio / MSVC
# -----------------------------------------------------------------------
Write-Host "Compilers:" -ForegroundColor White

# Directly locate cl.exe for a given VS install + target architecture by reading
# the toolset version file and constructing the expected path.  Works even when
# vcvarsall.bat fails to set up the environment (e.g. VC.CoreBuildTools missing).
function Find-ClExe($vsRoot, $targetArch) {
    $verFile = Join-Path $vsRoot "VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt"
    if (-not (Test-Path $verFile)) { return $null }
    $toolsVer = (Get-Content $verFile).Trim()
    # Prefer native host; fall back to cross-host
    $hostArchCandidates = switch ($targetArch) {
        "arm64" { @("Hostarm64\arm64", "Hostx64\arm64") }
        "x64"   { @("Hostx64\x64", "Hostarm64\x64") }
        default { @("Hostx64\$targetArch") }
    }
    foreach ($sub in $hostArchCandidates) {
        $cl = Join-Path $vsRoot "VC\Tools\MSVC\$toolsVer\bin\$sub\cl.exe"
        if (Test-Path $cl) { return $cl }
    }
    return $null
}

# vswhere lives under the VS Installer; on ARM64 hosts the installer is native (no (x86))
$vswhere = $null
foreach ($p in @(
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
    "$env:ProgramFiles\Microsoft Visual Studio\Installer\vswhere.exe"
)) { if (Test-Path $p) { $vswhere = $p; break } }
if (-not $vswhere) {
    $vswhere = (Get-Command vswhere -ErrorAction SilentlyContinue).Source
}

# Locate the VS installation root
$vsPath = $null
if ($vswhere) {
    $vsPath = & $vswhere -latest -products * `
        -property installationPath 2>$null | Select-Object -First 1
}

# Fallback: probe well-known VS installation paths when vswhere is absent or returned nothing
# Try VS 2026 (version 18) first, then VS 2022 (version 17)
if (-not $vsPath) {
    foreach ($root in @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\18\BuildTools",
        "$env:ProgramFiles\Microsoft Visual Studio\18\BuildTools",
        "$env:ProgramFiles\Microsoft Visual Studio\18\Enterprise",
        "$env:ProgramFiles\Microsoft Visual Studio\18\Professional",
        "$env:ProgramFiles\Microsoft Visual Studio\18\Community",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\BuildTools",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\Enterprise",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\Professional",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\Community"
    )) {
        if (Test-Path (Join-Path $root "VC\Auxiliary\Build\vcvarsall.bat")) {
            $vsPath = $root; break
        }
    }
}

# --- Detect cl.exe for the PRIMARY platform ---
$msvcVer = $null
$usedDirectProbe = $false
if ($vsPath) {
    # Method 1: vcvarsall (sets full build environment)
    $vcvarsall = Join-Path $vsPath "VC\Auxiliary\Build\vcvarsall.bat"
    $clVerOutput = cmd /c "`"$vcvarsall`" $primaryVcvarsArg >nul 2>&1 && cl.exe 2>&1" 2>&1
    $msvcVer = ($clVerOutput | Select-String "Version\s+([\d.]+)" |
                ForEach-Object { $_.Matches[0].Groups[1].Value }) | Select-Object -First 1

    # Method 2: direct filesystem probe (works when VC workload is incomplete)
    if (-not $msvcVer) {
        $directCl = Find-ClExe $vsPath $primaryPlatform
        if ($directCl) {
            $clVerOutput = & $directCl 2>&1
            $msvcVer = ($clVerOutput | Select-String "Version\s+([\d.]+)" |
                        ForEach-Object { $_.Matches[0].Groups[1].Value }) | Select-Object -First 1
            if ($msvcVer) { $usedDirectProbe = $true }
        }
    }
}

$script:vcvarsallBroken = $false
if ($vsPath -and $msvcVer) {
    $minVer = [version]"14.50"
    $curMajMin = [version]($msvcVer -replace '^(\d+\.\d+).*', '$1')
    if ($curMajMin -ge $minVer) {
        Write-Status "MSVC $primaryPlatform (cl.exe)" "OK" "v$msvcVer at $vsPath"
    } else {
        Write-Status "MSVC $primaryPlatform (cl.exe)" "WARN" "v$msvcVer found (need >= 14.50)"
    }
    # Warn if vcvarsall didn't work (detected via direct probe only)
    if ($usedDirectProbe) {
        $script:vcvarsallBroken = $true
        Write-Status "vcvarsall.bat" "WARN" "cl.exe found but vcvarsall cannot set up the build environment"
        Write-Host "         -> VC workload incomplete. Open Visual Studio Installer, click Modify on" -ForegroundColor DarkYellow
        Write-Host "            your Build Tools, and enable 'Desktop development with C++' workload." -ForegroundColor DarkYellow
    }
} else {
    Write-Status "MSVC $primaryPlatform tools" "MISS" "Visual Studio 2026 (or 2022) with $primaryPlatform C++ workload required"
    Install-IfMissing "Visual Studio Build Tools" "Microsoft.VisualStudio.2026.BuildTools" $false
}

# -----------------------------------------------------------------------
# 2. LLVM / clang-cl
# -----------------------------------------------------------------------
$clangcl = $null
$llvmVer = $null

# Check common locations
$llvmPaths = @(
    "$env:LLVM_PATH\clang-cl.exe",
    "C:\Program Files\LLVM\bin\clang-cl.exe",
    "C:\Program Files (x86)\LLVM\bin\clang-cl.exe"
)
if ($vsPath) {
    $llvmPaths += Join-Path $vsPath "VC\Tools\Llvm\ARM64\bin\clang-cl.exe"
}

foreach ($p in $llvmPaths) {
    if (Test-Path $p) { $clangcl = $p; break }
}
if (-not $clangcl) {
    $clangcl = (Get-Command clang-cl -ErrorAction SilentlyContinue).Source
}

if ($clangcl) {
    $llvmVerOutput = & $clangcl --version 2>&1
    $llvmVer = ($llvmVerOutput | Select-String "clang version\s+([\d.]+)" |
                ForEach-Object { $_.Matches[0].Groups[1].Value }) | Select-Object -First 1
    if ($llvmVer) {
        $minLlvm = [version]"21.0"
        $curLlvm = [version]($llvmVer -replace '^(\d+\.\d+).*', '$1')
        if ($curLlvm -ge $minLlvm) {
            Write-Status "LLVM (clang-cl)" "OK" "v$llvmVer at $clangcl"
        } else {
            Write-Status "LLVM (clang-cl)" "WARN" "v$llvmVer found (need >= 21.0)"
        }
    } else {
        Write-Status "LLVM (clang-cl)" "WARN" "Found at $clangcl but couldn't determine version"
    }
} else {
    Write-Status "LLVM (clang-cl)" "MISS" ""
    Install-IfMissing "LLVM" "LLVM.LLVM" $false
}

# Check lld-link alongside clang-cl
if ($clangcl) {
    $lldLink = Join-Path (Split-Path $clangcl) "lld-link.exe"
    if (Test-Path $lldLink) {
        Write-Status "lld-link" "OK" $lldLink
    } else {
        Write-Status "lld-link" "WARN" "Not found alongside clang-cl; LTO linking will fail"
    }
}

# Check ClangCL MSBuild toolset integration (required for MSBuild /p:PlatformToolset=ClangCL)
if ($vsPath) {
    # Check ARM64 ClangCL toolset
    # Try v180 (VS 2026) first, then v170 (VS 2022)
    $toolsetDir = $null
    foreach ($vcVer in @("v180", "v170")) {
        $candidate = Join-Path $vsPath "MSBuild\Microsoft\VC\$vcVer\Platforms\ARM64\PlatformToolsets\ClangCL"
        if (Test-Path $candidate) { $toolsetDir = $candidate; break }
    }
    if ($toolsetDir) {
        Write-Status "ClangCL toolset (arm64)" "OK" "MSBuild integration present"
    } else {
        Write-Status "ClangCL toolset (arm64)" "MISS" "MSBuild cannot use PlatformToolset=ClangCL for ARM64"
        Write-Host "         -> Open Visual Studio Installer -> Modify -> Individual components" -ForegroundColor DarkYellow
        Write-Host "         -> Install 'C++ Clang Compiler for Windows' and 'MSBuild support for LLVM (clang-cl) toolset'" -ForegroundColor DarkYellow
    }
}

Write-Host ""
Write-Host "Build tools:" -ForegroundColor White

# -----------------------------------------------------------------------
# 3. Python (with pymanager support)
# -----------------------------------------------------------------------
$pymanagerOk = Test-Command "pymanager"
if ($pymanagerOk) {
    Write-Status "Python Manager (pymanager)" "OK" "available"
}

$pythonOk = Test-Command "python"
if ($pythonOk) {
    $pyVer = (python --version 2>&1) -replace 'Python\s+', ''
    $pyArch = python -c "import struct; print(struct.calcsize('P')*8)" 2>&1
    $pyArchLabel = if ($pyArch -eq "64") {
        $pyPlatform = python -c "import platform; print(platform.machine())" 2>&1
        if ($pyPlatform -match "ARM64|aarch64") { "arm64" } else { "x64" }
    } else { "x86" }
    Write-Status "Python" "OK" "v$pyVer ($pyArchLabel)"

    # Warn if Python is not native ARM64
    if ($pyArchLabel -ne "arm64") {
        Write-Status "Python (native)" "WARN" "Running $pyArchLabel Python — native arm64 Python required for benchmarks"
        if ($pymanagerOk) {
            Write-Host "         -> Install native: pymanager install 3.14-arm64" -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Status "Python" "MISS" ""
    if ($pymanagerOk) {
        if ($Install) {
            Write-Host "         -> Installing Python via pymanager..." -ForegroundColor Cyan
            & pymanager install "3.14-arm64"
        } else {
            Write-Host "         -> Install with: pymanager install 3.14-arm64" -ForegroundColor DarkYellow
        }
    } else {
        Install-IfMissing "Python Manager" "9NQ7512CXL7T" $false
        Write-Host "         -> Then: pymanager install 3.14-arm64" -ForegroundColor DarkYellow
    }
}

# -----------------------------------------------------------------------
# 3b. Virtual environment
# -----------------------------------------------------------------------
$venvActive = $null -ne $env:VIRTUAL_ENV
$venvExists = Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\activate.ps1")
if ($venvActive) {
    Write-Status "Virtual env" "OK" $env:VIRTUAL_ENV
} elseif ($venvExists) {
    Write-Status "Virtual env" "WARN" ".venv exists but is not activated"
    Write-Host "         -> Run: .venv\Scripts\activate" -ForegroundColor DarkYellow
} else {
    Write-Status "Virtual env" "WARN" "No .venv found — pip-installed tools (meson, ninja, invoke) won't be on PATH"
    Write-Host "         -> Run: python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt" -ForegroundColor DarkYellow
}

# -----------------------------------------------------------------------
# 4. Git
# -----------------------------------------------------------------------
$gitOk = Test-Command "git"
if ($gitOk) {
    $gitVer = (git --version 2>&1) -replace 'git version\s+', ''
    Write-Status "Git" "OK" "v$gitVer"
} else {
    Write-Status "Git" "MISS" ""
    Install-IfMissing "Git" "Git.Git" $false
}

# -----------------------------------------------------------------------
# 5. SVN (for LAME)
# -----------------------------------------------------------------------
$svnOk = Test-Command "svn"
if ($svnOk) {
    $svnVer = ((svn --version --quiet 2>&1) | Select-Object -First 1)
    Write-Status "SVN" "OK" "v$svnVer"
} else {
    Write-Status "SVN" "MISS" "Required for LAME checkout"
    Install-IfMissing "SlikSVN (CLI)" "Slik.Subversion" $false
}

# -----------------------------------------------------------------------
# 6. Meson
# -----------------------------------------------------------------------
$mesonOk = Test-Command "meson"
if ($mesonOk) {
    $mesonVer = ((meson --version 2>&1) | Select-Object -First 1)
    Write-Status "Meson" "OK" "v$mesonVer"
} else {
    Write-Status "Meson" "MISS" "Needed for NumPy"
    if (-not $venvActive) {
        Write-Host "         -> Activate venv first, then: pip install -r requirements.txt" -ForegroundColor DarkYellow
    } else {
        Write-Host "         -> Install with: pip install meson" -ForegroundColor DarkYellow
    }
}

# -----------------------------------------------------------------------
# 7. Ninja
# -----------------------------------------------------------------------
$ninjaOk = Test-Command "ninja"
if ($ninjaOk) {
    $ninjaVer = ((ninja --version 2>&1) | Select-Object -First 1)
    Write-Status "Ninja" "OK" "v$ninjaVer"
} else {
    Write-Status "Ninja" "MISS" "Needed for Meson/NumPy builds"
    if (-not $venvActive) {
        Write-Host "         -> Activate venv first, then: pip install -r requirements.txt" -ForegroundColor DarkYellow
    } else {
        Write-Host "         -> Install with: pip install ninja" -ForegroundColor DarkYellow
    }
}

# -----------------------------------------------------------------------
# 8. CMake
# -----------------------------------------------------------------------
$cmakeOk = Test-Command "cmake"
if ($cmakeOk) {
    $cmakeVer = ((cmake --version 2>&1) | Select-Object -First 1) -replace 'cmake version\s+', ''
    Write-Status "CMake" "OK" "v$cmakeVer"
} else {
    Write-Status "CMake" "MISS" "Needed for Blender"
    Install-IfMissing "CMake" "Kitware.CMake" $false
}

Write-Host ""
Write-Host "Profiling:" -ForegroundColor White

# -----------------------------------------------------------------------
# 9. Windows Performance Toolkit (xperf)
# -----------------------------------------------------------------------
$xperfPaths = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\Windows Performance Toolkit\xperf.exe",
    "$env:ProgramFiles\Windows Kits\10\Windows Performance Toolkit\xperf.exe"
)
$xperf = $null
foreach ($p in $xperfPaths) {
    if (Test-Path $p) { $xperf = $p; break }
}
if (-not $xperf) { $xperf = (Get-Command xperf -ErrorAction SilentlyContinue).Source }

if ($xperf) {
    Write-Status "xperf (WPT)" "OK" $xperf
} else {
    Write-Status "xperf (WPT)" "WARN" "Install Windows Performance Toolkit (part of Windows ADK)"
}

# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
Write-Host ""
if ($script:allGood) {
    Write-Host "All required tools detected. Ready to build!" -ForegroundColor Green
} else {
    Write-Host "Some tools are missing or outdated. See above for details." -ForegroundColor Yellow
    if (-not $Install) {
        Write-Host "Run with -Install to attempt automatic installation." -ForegroundColor DarkYellow
    }
}
Write-Host ""
