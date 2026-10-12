param(
    [string]$Version = (Get-Content -Raw (Join-Path $PSScriptRoot 'VERSION')).Trim()
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$ReleaseRoot = Join-Path $Root 'release'
$PackageName = 'ElectrochemHarness-v' + $Version
$Stage = Join-Path $ReleaseRoot $PackageName
$ZipPath = Join-Path $ReleaseRoot ($PackageName + '.zip')
$HashPath = $ZipPath + '.sha256'

$AllowedFiles = @(
    'run_sci_origin.ps1',
    'run_sci.py',
    'run_gui.py',
    'start_gui.cmd',
    'run_land.py',
    'run_demo.py',
    'origin_plot.py',
    'check_environment.ps1',
    'build_release.ps1',
    '.gitignore',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'VERSION',
    'CHANGELOG.md',
    'LICENSE.txt'
)
$AllowedDirectories = @('src', 'examples', 'tests', '.github')

New-Item -ItemType Directory -Force $ReleaseRoot | Out-Null
if (Test-Path $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
if (Test-Path $HashPath) { Remove-Item -LiteralPath $HashPath -Force }
New-Item -ItemType Directory -Force $Stage | Out-Null

foreach ($relative in $AllowedFiles) {
    $source = Join-Path $Root $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw ('Required release file is missing: ' + $relative)
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $Stage $relative)
}
$releaseReadme = Get-ChildItem -LiteralPath $Root -File -Filter 'README_*.md' |
    Sort-Object Name | Select-Object -First 1
if (-not $releaseReadme) {
    throw 'Release README matching README_*.md is missing.'
}
Copy-Item -LiteralPath $releaseReadme.FullName -Destination (Join-Path $Stage 'README.md')
foreach ($relative in $AllowedDirectories) {
    $source = Join-Path $Root $relative
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw ('Required release directory is missing: ' + $relative)
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $Stage $relative) -Recurse
}

$knowledge = Join-Path $Stage 'knowledge'
New-Item -ItemType Directory -Force $knowledge | Out-Null
Copy-Item -LiteralPath (Join-Path $Root 'knowledge\base_rules.json') -Destination $knowledge
[System.IO.File]::WriteAllText(
    (Join-Path $knowledge 'experiences.jsonl'),
    '',
    (New-Object System.Text.UTF8Encoding($false))
)
New-Item -ItemType Directory -Force (Join-Path $Stage 'outputs') | Out-Null

Get-ChildItem -Path $Stage -Directory -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $Stage -File -Recurse -Include '*.pyc', '*.pyo' -ErrorAction SilentlyContinue |
    Remove-Item -Force

Compress-Archive -LiteralPath $Stage -DestinationPath $ZipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(
    $HashPath,
    ($hash + '  ' + [System.IO.Path]::GetFileName($ZipPath) + [Environment]::NewLine),
    (New-Object System.Text.UTF8Encoding($false))
)
Remove-Item -LiteralPath $Stage -Recurse -Force

Write-Host ('ZIP=' + $ZipPath)
Write-Host ('SHA256=' + $hash)
Write-Host ('CHECKSUM=' + $HashPath)
