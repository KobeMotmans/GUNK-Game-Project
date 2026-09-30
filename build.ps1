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
# Let op: sinds PyInstaller 6 heet de map _tcl_data en niet meer tcl.
# Met de oude naam vond Test-Path niets en werd er stilletjes niets gewist.
$tclTzdata = Join-Path (Join-Path (Join-Path $gunkDir "_internal") "_tcl_data") "tzdata"
if (Test-Path $tclTzdata) {
    Remove-Item -Path $tclTzdata -Recurse -Force
    Write-Host "[BUILD] TCL tzdata verwijderd" -ForegroundColor Yellow
} else {
    Write-Host "[BUILD] LET OP: geen tzdata-map gevonden op $tclTzdata" -ForegroundColor Red
}

# Opschonen van _internal. Alles hieronder is los geverifieerd: de exe is na
# elke stap gestart en bleef op 'pygame window' met een geslaagde preload.
# Staat er ooit iets tussen dat de game wél nodig heeft, dan breekt de exe pas
# bij het spelen. Vandaar de luide logregels per verwijdering.
$internalDir = Join-Path $gunkDir "_internal"
$removedKB = 0

# a) PyInstaller zet de SDL/freetype-DLL's zowel in _internal als in
#    _internal\pygame. De Windows-lader zoekt in de exemap, dus de kopie in de
#    pygame-map is ballast. 10 bestanden, ~2,1 MB.
$pygameDlls = Get-ChildItem (Join-Path $internalDir "pygame") -Filter *.dll -ErrorAction SilentlyContinue
if ($pygameDlls) {
    $kb = [math]::Round(($pygameDlls | Measure-Object Length -Sum).Sum / 1KB)
    foreach ($f in $pygameDlls) { Remove-Item -LiteralPath $f.FullName -Force }
    $removedKB += $kb
    Write-Host "[BUILD] $kb KB dubbele pygame-DLL's verwijderd" -ForegroundColor Yellow
}

# b) Pillow laadt _avif pas als er een AVIF-bestand voorkomt. Het spel is
#    overal PNG en OGG, dus dit is nooit nodig. ~1,8 MB.
$avif = Get-ChildItem $internalDir -Recurse -Filter "*avif*" -ErrorAction SilentlyContinue
if ($avif) {
    $kb = [math]::Round(($avif | Measure-Object Length -Sum).Sum / 1KB)
    foreach ($f in $avif) { Remove-Item -LiteralPath $f.FullName -Force }
    $removedKB += $kb
    Write-Host "[BUILD] $kb KB ongebruikte AVIF-ondersteuning verwijderd" -ForegroundColor Yellow
}

# c) OpenSSL. Het spel doet geen TLS en gebruikt alleen UDP-sockets, dus
#    libcrypto/libssl worden nergens geladen. ~1,3 MB.
$crypto = @("libcrypto-1_1.dll", "libssl-1_1.dll") | ForEach-Object { Join-Path $internalDir $_ } | Where-Object { Test-Path $_ }
if ($crypto) {
    $kb = 0
    foreach ($f in $crypto) { $kb += [math]::Round((Get-Item $f).Length / 1KB); Remove-Item -LiteralPath $f -Force }
    $removedKB += $kb
    Write-Host "[BUILD] $kb KB ongebruikte OpenSSL-DLL's verwijderd" -ForegroundColor Yellow
}
if ($removedKB -gt 0) {
    Write-Host "[BUILD] _internal opgeschoond: samen $removedKB KB" -ForegroundColor Green
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
