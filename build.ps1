param(
    [string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    [string]$ISCC = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── 1. UPX ───────────────────────────────────────────────────
$upxDir = Join-Path (Join-Path $root "tools") "upx"
$upxExe = Join-Path $upxDir "upx.exe"

if (-not (Test-Path $upxExe)) {
    Write-Host "[BUILD] UPX niet gevonden, downloaden..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $upxDir -Force | Out-Null
    $url = "https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-win64.zip"
    $zip = Join-Path $upxDir "upx.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $upxDir -Force
    $sub = Get-ChildItem -Path $upxDir -Directory | Select-Object -First 1
    if ($sub) {
        Move-Item -Path (Join-Path $sub.FullName "upx.exe") -Destination $upxDir -Force
        Remove-Item -Path $sub.FullName -Recurse -Force
    }
    Remove-Item -Path $zip -Force
    Write-Host "[BUILD] UPX gedownload" -ForegroundColor Green
}

if (Test-Path $upxExe) {
    $env:Path = "$upxDir;$env:Path"
}

# ── 2. Schoon oude build ─────────────────────────────────────
$distDir = Join-Path $root "dist"
$buildDir = Join-Path $root "build"
$outputDir = Join-Path $root "Output"
if (Test-Path $distDir) { Remove-Item -Path $distDir -Recurse -Force }
if (Test-Path $buildDir) { Remove-Item -Path $buildDir -Recurse -Force }
if (Test-Path $outputDir) { Remove-Item -Path $outputDir -Recurse -Force -ErrorAction SilentlyContinue }

# ── 3. PyInstaller ───────────────────────────────────────────
Write-Host "[BUILD] PyInstaller..." -ForegroundColor Cyan
& $Python -m PyInstaller (Join-Path $root "game.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "[BUILD] PyInstaller OK" -ForegroundColor Green

# ── 4. Post-build: move assets uit _internal/ naar root ─────
$gunkDir = Join-Path $distDir "GUNK"
$internalAssets = Join-Path (Join-Path $gunkDir "_internal") "assets"
$rootAssets = Join-Path $gunkDir "assets"
if (Test-Path $internalAssets) {
    if (Test-Path $rootAssets) { Remove-Item -Path $rootAssets -Recurse -Force }
    Move-Item -Path $internalAssets -Destination $gunkDir
    Write-Host "[BUILD] Assets verplaatst naar root" -ForegroundColor Yellow
}

# Cleanup tcl timezone data (in _internal)
$tclTzdata = Join-Path (Join-Path (Join-Path $gunkDir "_internal") "tcl") "tzdata"
if (Test-Path $tclTzdata) {
    Remove-Item -Path $tclTzdata -Recurse -Force
    Write-Host "[BUILD] TCL tzdata verwijderd" -ForegroundColor Yellow
}

# ── 5. Inno Setup installer ──────────────────────────────────
if (-not $ISCC) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup\ISCC.exe",
        "C:\Program Files\Inno Setup\ISCC.exe"
    )
    $ISCC = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ($ISCC -and (Test-Path $ISCC)) {
    Write-Host "[BUILD] Inno Setup..." -ForegroundColor Cyan
    & $ISCC (Join-Path $root "installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Write-Host "[BUILD] Installer OK" -ForegroundColor Green
} else {
    Write-Host "[BUILD] Inno Setup niet gevonden (zoekpaden: ISCC=$ISCC)" -ForegroundColor Yellow
}

# ── 6. Resultaat ─────────────────────────────────────────────
$setupFile = Get-ChildItem -Path (Join-Path $root "Output") -Filter "GUNK_Setup*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($setupFile) {
    $mb = [math]::Round($setupFile.Length / 1MB, 1)
    Write-Host "`n==============================" -ForegroundColor Cyan
    Write-Host "  BUILD COMPLETE" -ForegroundColor Green
    Write-Host "  EXE:       $($distDir)\GUNK\GUNK.exe"
    Write-Host "  Installer: $($setupFile.FullName)"
    Write-Host "  Grootte:   $mb MB"
    Write-Host "==============================" -ForegroundColor Cyan
} else {
    Write-Host "`n==============================" -ForegroundColor Cyan
    Write-Host "  BUILD COMPLETE" -ForegroundColor Green
    Write-Host "  EXE:       $($distDir)\GUNK\GUNK.exe"
    Write-Host "  (geen installer - Inno Setup niet gevonden)"
    Write-Host "==============================" -ForegroundColor Cyan
}
