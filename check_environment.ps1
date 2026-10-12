param(
    [string]$OriginExe,
    [switch]$RequireOrigin
)

$ErrorActionPreference = 'Continue'
$failures = 0
$compatPath = Join-Path $PSScriptRoot 'origin_compat.json'
$originCompat = if (Test-Path -LiteralPath $compatPath) {
    Get-Content -Raw -Encoding UTF8 $compatPath | ConvertFrom-Json
} else { $null }

function Write-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail, [bool]$Required = $true)
    $status = if ($Passed) { 'PASS' } elseif ($Required) { 'FAIL' } else { 'WARN' }
    Write-Host ('[{0}] {1}: {2}' -f $status, $Name, $Detail)
    if (-not $Passed -and $Required) { $script:failures++ }
}

function Get-OriginRelease {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path
    $text = @($item.FullName, $item.VersionInfo.ProductName, $item.VersionInfo.FileDescription) -join ' '
    $match = [regex]::Match($text, '(?i)(?<!\d)(202[1-6]b?)(?!\d)')
    if ($match.Success) { return $match.Groups[1].Value.ToLowerInvariant() }
    return $null
}

Write-Check 'PowerShell' ($PSVersionTable.PSVersion.Major -ge 5) ([string]$PSVersionTable.PSVersion)
$pythonDetail = 'not found'
$pythonOk = $false
$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $pythonDetail = (& $py.Source -3 -c "import sys, tkinter; print(sys.version.split()[0] + ' / Tk ' + str(tkinter.TkVersion)); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>&1 | Out-String).Trim()
    $pythonOk = $LASTEXITCODE -eq 0
} elseif ($python) {
    $pythonDetail = (& $python.Source -c "import sys, tkinter; print(sys.version.split()[0] + ' / Tk ' + str(tkinter.TkVersion)); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>&1 | Out-String).Trim()
    $pythonOk = $LASTEXITCODE -eq 0
}
Write-Check 'Python 3.10+' $pythonOk $pythonDetail
Write-Check 'Origin compatibility matrix' ([bool]$originCompat) 'origin_compat.json (2021 through 2026b)'

$originCandidate = $null
if ($OriginExe -and (Test-Path -LiteralPath $OriginExe -PathType Leaf)) {
    $originCandidate = (Resolve-Path -LiteralPath $OriginExe).Path
} else {
    $patterns = @()
    if ($env:ProgramFiles) { $patterns += (Join-Path $env:ProgramFiles 'OriginLab\Origin*\Origin64.exe') }
    if (${env:ProgramFiles(x86)}) { $patterns += (Join-Path ${env:ProgramFiles(x86)} 'OriginLab\Origin*\Origin64.exe') }
    foreach ($drive in @('C:', 'D:', 'E:')) {
        if (Test-Path ($drive + '\')) { $patterns += ($drive + '\Origin*\Origin64.exe') }
    }
    $found = foreach ($pattern in $patterns) {
        Get-Item -Path $pattern -ErrorAction SilentlyContinue
    }
    $originCandidate = $found | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName -First 1
}
$originRelease = Get-OriginRelease -Path $originCandidate
$supportedOrigin = [bool]($originRelease -and $originCompat -and ($originCompat.supported_releases -contains $originRelease))
$originDetail = if ($supportedOrigin) {
    '{0} (supported release {1})' -f $originCandidate, $originRelease
} elseif ($originCandidate) {
    $originCandidate + ' (release outside 2021–2026b or undetected)'
} else {
    'not found; use report-only mode'
}
Write-Check 'Origin (optional)' $supportedOrigin $originDetail $RequireOrigin

$simsun = Test-Path (Join-Path $env:WINDIR 'Fonts\simsun.ttc')
$times = (Test-Path (Join-Path $env:WINDIR 'Fonts\times.ttf')) -or (Test-Path (Join-Path $env:WINDIR 'Fonts\timesbd.ttf'))
Write-Check 'SimSun font' $simsun 'required for Chinese plot text' $false
Write-Check 'Times New Roman font' $times 'required for Latin plot text' $false

$networkOk = $false
$networkDetail = 'Crossref unavailable; literature comparison will be skipped'
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri 'https://api.crossref.org/works?rows=0' -Method Get -TimeoutSec 15
    $networkOk = $response.StatusCode -eq 200
    if ($networkOk) { $networkDetail = 'Crossref reachable' }
} catch { $networkDetail = $_.Exception.Message }
Write-Check 'Literature network (optional)' $networkOk $networkDetail $false

if ($failures -gt 0) {
    Write-Host ("Environment check finished with {0} required failure(s)." -f $failures)
    exit 1
}
Write-Host 'Environment check passed. Optional warnings only affect the named feature.'
exit 0
