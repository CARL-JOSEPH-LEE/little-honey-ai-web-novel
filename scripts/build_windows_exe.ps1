param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$Name = -join ([char[]](0x5C0F, 0x871C, 0x0041, 0x0049, 0x7F51, 0x6587))
$InternalName = "XiaomiAINovel"
$IssuerName = -join ([char[]](0x5C0F, 0x871C, 0x0041, 0x0049, 0x6388, 0x6743, 0x7801, 0x751F, 0x6210, 0x5668))
$IssuerInternalName = "XiaomiAILicenseIssuer"

Write-Host "==> Install build dependencies"
python -m pip install --upgrade pip | Out-Null
python -m pip install -e ".[build]" | Out-Null

if (-not $SkipTests) {
    Write-Host "==> Run tests"
    python -m unittest discover -s tests -v
} else {
    Write-Host "==> Skip tests"
}

Write-Host "==> Build $Name.exe with PyInstaller"
python -m PyInstaller --noconfirm --clean "DeepSeekNovelWriter.spec"

Write-Host "==> Build $IssuerName.exe with PyInstaller"
python -m PyInstaller --noconfirm --clean "LicenseIssuer.spec"

$BuiltExe = Join-Path $Root "dist\$InternalName.exe"
if (-not (Test-Path $BuiltExe)) {
    throw "Build failed: $BuiltExe was not generated"
}
$BuiltIssuerExe = Join-Path $Root "dist\$IssuerInternalName.exe"
if (-not (Test-Path $BuiltIssuerExe)) {
    throw "Build failed: $BuiltIssuerExe was not generated"
}

$Exe = Join-Path $Root "$Name.exe"
$IssuerExe = Join-Path $Root "$IssuerName.exe"
$ExistingExes = Get-ChildItem $Root -Filter "*.exe" -File
foreach ($ExistingExe in $ExistingExes) {
    try {
        Remove-Item $ExistingExe.FullName -Force
    } catch {
        Write-Host "Existing exe is locked, skipped: $($ExistingExe.FullName)"
    }
}
Move-Item $BuiltExe $Exe -Force
Move-Item $BuiltIssuerExe $IssuerExe -Force
Remove-Item (Join-Path $Root "dist") -Recurse -Force

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $Exe"
Write-Host "  $IssuerExe"
Write-Host ""
Write-Host "Seller checklist:"
Write-Host "  1. Send $Name.exe to customer."
Write-Host "  2. Keep seller_private_key.json private."
Write-Host "  3. Customer runs exe, copies machine code from Settings."
Write-Host "  4. Seller runs $IssuerName.exe with machine code and days."
Write-Host "  5. Customer pastes DSBK1 activation code in Settings."
