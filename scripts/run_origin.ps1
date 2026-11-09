param(
    [Parameter(Mandatory=$true)][string]$JobPath,
    [string]$OriginExe
)

$ErrorActionPreference = 'Stop'
$job = Get-Content -Raw -Encoding UTF8 -LiteralPath $JobPath | ConvertFrom-Json
$statusPath = [string]$job.status_path
if (Test-Path -LiteralPath $statusPath) { Remove-Item -LiteralPath $statusPath -Force }

function Resolve-OriginExe {
    param([string]$ExplicitPath)
    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) { throw 'The supplied Origin executable does not exist.' }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    if ($env:ELECTROCHEM_ORIGIN_EXE -and (Test-Path -LiteralPath $env:ELECTROCHEM_ORIGIN_EXE -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $env:ELECTROCHEM_ORIGIN_EXE).Path
    }
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Origin64.exe', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Origin64.exe')) {
        if (Test-Path $key) {
            $candidate = (Get-Item $key).GetValue('')
            if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return (Resolve-Path -LiteralPath $candidate).Path }
        }
    }
    throw 'Origin64.exe was not found through its App Paths registration. Set ELECTROCHEM_ORIGIN_EXE or pass -OriginExe.'
}

$originPath = Resolve-OriginExe -ExplicitPath $OriginExe
$originRelease = 'unknown'
$versionText = ((Get-Item -LiteralPath $originPath).VersionInfo | Out-String)
if ($versionText -match '(?i)(202[1-6]b?)') { $originRelease = $matches[1].ToLowerInvariant() }
$runtime = Join-Path $PSScriptRoot '.origin-runtime'
$runtimeRun = Join-Path $runtime ('job_' + $PID)
New-Item -ItemType Directory -Force -Path $runtimeRun | Out-Null
$runtimeScript = Join-Path $runtimeRun 'origin_plot.py'
$runtimeEngine = Join-Path $runtimeRun 'origin_plot_engine.py'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'origin_plot.py') -Destination $runtimeScript -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'origin_plot_engine.py') -Destination $runtimeEngine -Force
$env:ELECTROCHEM_ORIGIN_JOB = (Resolve-Path -LiteralPath $JobPath).Path
$env:ELECTROCHEM_ORIGIN_RELEASE = $originRelease

$process = Get-Process Origin64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $process) { Start-Process -FilePath $originPath | Out-Null; Start-Sleep -Seconds 8 }
$origin = New-Object -ComObject Origin.ApplicationSI
$origin.Visible = 1
$origin.Execute(('run -pyf "{0}";' -f $runtimeScript.Replace('\', '/'))) | Out-Null
$deadline = (Get-Date).AddSeconds(180)
while (-not (Test-Path -LiteralPath $statusPath) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
if (-not (Test-Path -LiteralPath $statusPath)) { throw 'Origin did not produce a status file within 180 seconds.' }
$status = Get-Content -Raw -Encoding UTF8 -LiteralPath $statusPath | ConvertFrom-Json
if (-not $status.ok) { throw ('Origin plotting failed: ' + $status.error) }
Write-Output ('Origin project: ' + $status.project)
