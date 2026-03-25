<#
.SYNOPSIS
    Environment setup and validation for MSVC vs LLVM benchmarks.

.DESCRIPTION
    Detects and validates required tools: Visual Studio 2022 with x64 and ARM64 C++ tools,
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
    winget install --id $wingetId --accept-source-agreements --accept-package-agreements
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " MSVC vs LLVM Benchmark - Env Check"
Write-Host "=============================================" -ForegroundColor Cyan

# Detect host architecture
$hostArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLower()
if ($hostArch -eq "arm64") {
    $primaryPlatform = "arm64"
    $primaryComponent = "Microsoft.VisualStudio.Component.VC.Tools.ARM64"
    $primaryVcvarsArg = "arm64"
    $secondaryPlatform = "x64"
    $secondaryComponent = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
} else {
    $primaryPlatform = "x64"
    $primaryComponent = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"
    $primaryVcvarsArg = "x64"
    $secondaryPlatform = "arm64"
    $secondaryComponent = "Microsoft.VisualStudio.Component.VC.Tools.ARM64"
}
Write-Host " Host: $hostArch  |  Primary: $primaryPlatform  |  Secondary: $secondaryPlatform"
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------
# 1. Visual Studio / MSVC
# -----------------------------------------------------------------------
Write-Host "Compilers:" -ForegroundColor White

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    $vswhere = (Get-Command vswhere -ErrorAction SilentlyContinue).Source
}

$vsPath = $null
$msvcVer = $null
if ($vswhere) {
    # Check primary platform tools
    $vsPath = & $vswhere -latest -products * `
        -requires $primaryComponent `
        -property installationPath 2>$null | Select-Object -First 1

    if ($vsPath) {
        $vcvarsall = Join-Path $vsPath "VC\Auxiliary\Build\vcvarsall.bat"
        $clVerOutput = cmd /c "`"$vcvarsall`" $primaryVcvarsArg >nul 2>&1 && cl.exe 2>&1" 2>&1
        $msvcVer = ($clVerOutput | Select-String "Version\s+([\d.]+)" |
                    ForEach-Object { $_.Matches[0].Groups[1].Value }) | Select-Object -First 1
    }
}

if ($vsPath -and $msvcVer) {
    $minVer = [version]"14.50"
    $curMajMin = [version]($msvcVer -replace '^(\d+\.\d+).*', '$1')
    if ($curMajMin -ge $minVer) {
        Write-Status "MSVC $primaryPlatform (cl.exe)" "OK" "v$msvcVer at $vsPath"
    } else {
        Write-Status "MSVC $primaryPlatform (cl.exe)" "WARN" "v$msvcVer found (need >= 14.50)"
    }
} else {
    Write-Status "MSVC $primaryPlatform tools" "MISS" "Visual Studio 2022 with $primaryPlatform C++ workload required"
    Install-IfMissing "Visual Studio Build Tools" "Microsoft.VisualStudio.2022.BuildTools" $false
}

# Check secondary platform tools (optional)
if ($vswhere) {
    $vsPathSecondary = & $vswhere -latest -products * `
        -requires $secondaryComponent `
        -property installationPath 2>$null | Select-Object -First 1
    if ($vsPathSecondary) {
        Write-Status "MSVC $secondaryPlatform tools" "OK" "$secondaryPlatform C++ workload installed"
    } else {
        Write-Status "MSVC $secondaryPlatform tools" "WARN" "Not installed — needed for --platform=$secondaryPlatform"
    }
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
    $llvmPaths += Join-Path $vsPath "VC\Tools\Llvm\x64\bin\clang-cl.exe"
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

Write-Host ""
Write-Host "Build tools:" -ForegroundColor White

# -----------------------------------------------------------------------
# 3. Python
# -----------------------------------------------------------------------
$pythonOk = Test-Command "python"
if ($pythonOk) {
    $pyVer = (python --version 2>&1) -replace 'Python\s+', ''
    Write-Status "Python" "OK" "v$pyVer"
} else {
    Write-Status "Python" "MISS" ""
    Install-IfMissing "Python" "Python.Python.3.12" $false
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
    Write-Host "         -> Install with: pip install meson" -ForegroundColor DarkYellow
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
    Install-IfMissing "Ninja" "Ninja-build.Ninja" $false
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
