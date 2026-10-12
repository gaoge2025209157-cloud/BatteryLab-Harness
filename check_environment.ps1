param(
    [string]$OriginExe,
    [switch]$RequireOrigin
)

$ErrorActionPreference = 'Continue'
$failures = 0

function Write-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail, [bool]$Required = $true)
    $status = if ($Passed) { 'PASS' } elseif ($Required) { 'FAIL' } else { 'WARN' }
    Write-Host ('[{0}] {1}: {2}' -f $status, $Name, $Detail)
    if (-not $Passed -and $Required) { $script:failures++ }
}

$psOk = $PSVersionTable.PSVersion.Major -ge 5
Write-Check 'PowerShell' $psOk ([string]$PSVersionTable.PSVersion)

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
    foreach ($pattern in $patterns) {
        $found = Get-Item -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { $originCandidate = $found.FullName; break }
    }
}
$originDetail = if ($originCandidate) { $originCandidate } else { 'not found; use -SkipOrigin for report-only mode' }
Write-Check 'Origin (optional)' ([bool]$originCandidate) $originDetail $RequireOrigin

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
} catch {
    $networkDetail = $_.Exception.Message
}
Write-Check 'Literature network (optional)' $networkOk $networkDetail $false

if ($failures -gt 0) {
    Write-Host ("Environment check finished with {0} required failure(s)." -f $failures)
    exit 1
}
Write-Host 'Environment check passed. Optional warnings only affect the named feature.'
exit 0
