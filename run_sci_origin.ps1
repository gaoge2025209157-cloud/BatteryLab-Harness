param(
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [switch]$Guided,
    [switch]$SearchLiterature,
    [switch]$SkipOrigin,
    [ValidateRange(1, 200)][int]$MaxLiterature = 50,
    [string]$OriginExe,
    [string]$OriginRuntimeDir,
    [string]$BatterySystem,
    [string]$ActiveMaterial,
    [string]$CellType,
    [string]$CounterElectrode,
    [string]$TestCurrent,
    [string]$NormalizationBasis,
    [string]$Temperature,
    [string]$Material,
    [string]$CellConfiguration,
    [string]$Rate
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$compatPath = Join-Path $Root 'origin_compat.json'
if (-not (Test-Path -LiteralPath $compatPath -PathType Leaf)) {
    throw 'origin_compat.json is missing.'
}
$script:originCompat = Get-Content -Raw -Encoding UTF8 $compatPath | ConvertFrom-Json

function Get-OriginRelease {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path
    $versionInfo = $item.VersionInfo
    $text = @(
        $item.FullName,
        $versionInfo.ProductName,
        $versionInfo.FileDescription,
        $versionInfo.Comments
    ) -join ' '
    $match = [regex]::Match($text, '(?i)(?<!\d)(202[1-6]b?)(?!\d)')
    if (-not $match.Success) { return $null }
    $release = $match.Groups[1].Value.ToLowerInvariant()
    if ($script:originCompat.supported_releases -contains $release) { return $release }
    return $null
}

function Resolve-OriginExecutable {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw ('The supplied Origin executable does not exist: ' + $ExplicitPath)
        }
        $resolved = (Resolve-Path -LiteralPath $ExplicitPath).Path
        $release = Get-OriginRelease -Path $resolved
        if (-not $release) {
            throw 'The supplied Origin executable is outside the supported 2021–2026b range or its release cannot be detected.'
        }
        return [pscustomobject]@{ Path = $resolved; Release = $release }
    }

    $candidates = @()
    foreach ($key in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Origin64.exe',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Origin64.exe'
    )) {
        if (Test-Path $key) {
            $candidate = (Get-Item $key).GetValue('')
            if ($candidate) { $candidates += $candidate }
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
        if (Test-Path ($drive + '\')) { $patterns += ($drive + '\Origin*\Origin64.exe') }
    }
    foreach ($pattern in $patterns) {
        $candidates += Get-Item -Path $pattern -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }

    $supported = @()
    foreach ($candidate in ($candidates | Sort-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $release = Get-OriginRelease -Path $candidate
        if (-not $release) { continue }
        $year = [int]$release.Substring(0, 4)
        $score = $year * 10
        if ($release.EndsWith('b')) { $score++ }
        $supported += [pscustomobject]@{
            Path = (Resolve-Path -LiteralPath $candidate).Path
            Release = $release
            Score = $score
        }
    }
    $selected = $supported | Sort-Object Score -Descending | Select-Object -First 1
    if ($selected) { return $selected }
    throw 'No supported Origin installation was found. Supported releases are 2021 through 2026b. Pass -OriginExe or use -SkipOrigin.'
}

function Invoke-ProjectPython {
    param([string[]]$Arguments)
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $output = & $py.Source -3 @Arguments
        $code = $LASTEXITCODE
        $output | ForEach-Object { Write-Host $_ }
        return [int]$code
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $output = & $python.Source @Arguments
        $code = $LASTEXITCODE
        $output | ForEach-Object { Write-Host $_ }
        return [int]$code
    }
    throw 'Python 3 was not found. Install Python 3.10 or newer.'
}

$pythonArgs = @((Join-Path $Root 'run_sci.py'), $InputFile, '--output-dir', $OutputDir, '--max-literature', [string]$MaxLiterature)
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
if ($SkipOrigin) {
    Write-Host 'Origin plotting skipped. Report and Origin-ready CSV files were generated.'
    exit 0
}

$originInfo = Resolve-OriginExecutable -ExplicitPath $OriginExe
$resolvedOriginExe = $originInfo.Path
$origin_release = $originInfo.Release
$jobPath = Join-Path (Resolve-Path $OutputDir) 'origin_job.json'
$statusPath = Join-Path (Resolve-Path $OutputDir) 'origin_status.json'
if (Test-Path $statusPath) { Remove-Item $statusPath -Force }
$env:ELECTROCHEM_ORIGIN_JOB = $jobPath
$env:ELECTROCHEM_ORIGIN_RELEASE = $origin_release

$runtimeBase = $OriginRuntimeDir
if (-not $runtimeBase) {
    $runtimeCandidates = @($env:KIROCREW_SCRATCH, $env:TEMP, $Root, (Resolve-Path $OutputDir).Path)
    $runtimeBase = $runtimeCandidates |
        Where-Object { $_ -and ($_ -match '^[\x00-\x7F]+$') } |
        Select-Object -First 1
}
if (-not $runtimeBase -or $runtimeBase -notmatch '^[\x00-\x7F]+$') {
    throw 'Origin requires an ASCII runtime path for run -pyf. Pass -OriginRuntimeDir with an ASCII-only writable directory.'
}
New-Item -ItemType Directory -Force $runtimeBase | Out-Null
$runtimeDir = Join-Path $runtimeBase ('ElectrochemHarnessOrigin-' + $PID)
New-Item -ItemType Directory -Force $runtimeDir | Out-Null
$runtimeScriptPath = Join-Path $runtimeDir 'origin_plot.py'
Copy-Item -LiteralPath (Join-Path $Root 'origin_plot.py') -Destination $runtimeScriptPath -Force
$originScript = $runtimeScriptPath.Replace('\', '/')

$running = Get-Process Origin64 -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $resolvedOriginExe } | Select-Object -First 1
if (-not $running) {
    $started = Start-Process -FilePath $resolvedOriginExe -WorkingDirectory (Split-Path $resolvedOriginExe) -PassThru
    Start-Sleep -Seconds 10
    $started.Refresh()
    if ($started.HasExited) {
        throw ('Origin {0} exited during startup (code {1}). Open it manually once, then rerun.' -f $origin_release, $started.ExitCode)
    }
}

$origin = New-Object -ComObject Origin.ApplicationSI
$origin.Visible = 1
$originJobValue = $jobPath.Replace('\', '/')
$origin.Execute(('string ec_job$="{0}";string ec_release$="{1}";' -f $originJobValue, $origin_release)) | Out-Null
$origin.Execute(('run -pyf "{0}";' -f $originScript)) | Out-Null
$deadline = (Get-Date).AddSeconds(120)
while (-not (Test-Path $statusPath) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
if (-not (Test-Path $statusPath)) { throw 'Origin did not produce a status file within 120 seconds.' }
$status = Get-Content -Raw -Encoding UTF8 $statusPath | ConvertFrom-Json
if (-not $status.ok) { throw ("Origin plotting failed:`n" + $status.error) }
Write-Host ('Origin executable: ' + $resolvedOriginExe)
Write-Host ('Origin supported release: ' + $status.origin_release)
Write-Host ('originpro version: ' + $status.originpro_version)
if ($status.compatibility_warnings.Count -gt 0) {
    Write-Warning ('Origin compatibility fallbacks: ' + ($status.compatibility_warnings -join ' | '))
}
Write-Host ('Origin project: ' + $status.project)

Remove-Item -LiteralPath $runtimeDir -Recurse -Force -ErrorAction SilentlyContinue
