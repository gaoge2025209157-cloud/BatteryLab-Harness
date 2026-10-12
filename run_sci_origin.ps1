param(
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [switch]$Guided,
    [switch]$SearchLiterature,
    [switch]$SkipOrigin,
    [ValidateRange(1, 200)][int]$MaxLiterature = 50,
    [string]$OriginExe,
    [string]$BatterySystem,
    [string]$ActiveMaterial,
    [string]$CellType,
    [string]$CounterElectrode,
    [string]$TestCurrent,
    [string]$NormalizationBasis,
    [string]$Temperature,
    # Backward-compatible parameter names.
    [string]$Material,
    [string]$CellConfiguration,
    [string]$Rate
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Resolve-OriginExecutable {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw ('The supplied Origin executable does not exist: ' + $ExplicitPath)
        }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $appPathKeys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Origin64.exe',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Origin64.exe'
    )
    foreach ($key in $appPathKeys) {
        if (Test-Path $key) {
            $candidate = (Get-Item $key).GetValue('')
            if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        }
    }

    $patterns = @()
    if ($env:ProgramFiles) {
        $patterns += (Join-Path $env:ProgramFiles 'OriginLab\Origin*\Origin64.exe')
    }
    if (${env:ProgramFiles(x86)}) {
        $patterns += (Join-Path ${env:ProgramFiles(x86)} 'OriginLab\Origin*\Origin64.exe')
    }
    foreach ($drive in @('C:', 'D:', 'E:')) {
        if (Test-Path ($drive + '\')) {
            $patterns += ($drive + '\Origin*\Origin64.exe')
        }
    }
    foreach ($pattern in $patterns) {
        $candidate = Get-Item -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }

    throw 'Origin64.exe was not found. Install and start Origin once, or pass -OriginExe with its full path. Use -SkipOrigin to generate reports without Origin.'
}

function Invoke-ProjectPython {
    param([string[]]$Arguments)

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 @Arguments
        return $LASTEXITCODE
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @Arguments
        return $LASTEXITCODE
    }
    throw 'Python 3 was not found. Install Python 3.10 or newer and enable the py launcher or add python to PATH.'
}

$pythonArgs = @(
    (Join-Path $Root 'run_sci.py'),
    $InputFile,
    '--output-dir', $OutputDir,
    '--max-literature', [string]$MaxLiterature
)
if ($Guided) { $pythonArgs += '--guided' }
if ($SearchLiterature) { $pythonArgs += '--search-literature' }
if ($BatterySystem) { $pythonArgs += @('--battery-system', $BatterySystem) }
if ($ActiveMaterial) { $pythonArgs += @('--active-material', $ActiveMaterial) }
if ($CellType) { $pythonArgs += @('--cell-type', $CellType) }
if ($CounterElectrode) { $pythonArgs += @('--counter-electrode', $CounterElectrode) }
if ($TestCurrent) { $pythonArgs += @('--test-current', $TestCurrent) }
if ($NormalizationBasis) { $pythonArgs += @('--normalization-basis', $NormalizationBasis) }
if ($Temperature) { $pythonArgs += @('--temperature', $Temperature) }
if ($Material) { $pythonArgs += @('--material', $Material) }
if ($CellConfiguration) { $pythonArgs += @('--cell-configuration', $CellConfiguration) }
if ($Rate) { $pythonArgs += @('--rate', $Rate) }

$pythonExitCode = Invoke-ProjectPython -Arguments $pythonArgs
if ($pythonExitCode -ne 0) { exit $pythonExitCode }

Write-Host ('Concise report: ' + (Join-Path (Resolve-Path $OutputDir) '关键参数报告.md'))
if (Test-Path (Join-Path $OutputDir '文献证据.json')) {
    Write-Host ('Literature evidence: ' + (Join-Path (Resolve-Path $OutputDir) '文献证据.json'))
}
if ($SkipOrigin) {
    Write-Host 'Origin plotting skipped by request. Report and Origin-ready CSV files were generated.'
    exit 0
}

$resolvedOriginExe = Resolve-OriginExecutable -ExplicitPath $OriginExe
$jobPath = Join-Path (Resolve-Path $OutputDir) 'origin_job.json'
$statusPath = Join-Path (Resolve-Path $OutputDir) 'origin_status.json'
if (Test-Path $statusPath) { Remove-Item $statusPath -Force }
$env:ELECTROCHEM_ORIGIN_JOB = $jobPath
$originScript = (Join-Path $Root 'origin_plot.py').Replace('\', '/')

$running = Get-Process Origin64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $running) {
    $started = Start-Process -FilePath $resolvedOriginExe -WorkingDirectory (Split-Path $resolvedOriginExe) -PassThru
    Start-Sleep -Seconds 10
    $started.Refresh()
    if ($started.HasExited) {
        throw ('Origin exited during startup (code {0}). Open it manually once to finish license/user initialization, then rerun this command.' -f $started.ExitCode)
    }
}

# ApplicationCOMSI launches a COM-exclusive Origin instance, so an existing
# interactive project is not reused or overwritten.
$origin = New-Object -ComObject Origin.ApplicationCOMSI
$origin.Visible = 1
$origin.Execute(('run -pyf "{0}";' -f $originScript)) | Out-Null

$deadline = (Get-Date).AddSeconds(120)
while (-not (Test-Path $statusPath) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
}
if (-not (Test-Path $statusPath)) {
    throw 'Origin did not produce a status file within 120 seconds.'
}
$status = Get-Content -Raw -Encoding UTF8 $statusPath | ConvertFrom-Json
if (-not $status.ok) {
    throw ("Origin plotting failed:`n" + $status.error)
}
Write-Host ('Origin executable: ' + $resolvedOriginExe)
Write-Host ('Origin project: ' + $status.project)
