[CmdletBinding()]
param(
    [switch]$SkipPull,
    [switch]$LoadOlist
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseCompose = Join-Path $projectRoot "compose.release.yaml"
$environmentFile = Join-Path $projectRoot ".env"
$virtualEnvironment = Join-Path $projectRoot ".venv"
$virtualEnvironmentPython = Join-Path $virtualEnvironment "Scripts\python.exe"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Executable,
        [Parameter(ValueFromRemainingArguments)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

function Test-DataPilotPython {
    param(
        [Parameter(Mandatory)]
        [string]$PythonExecutable
    )

    & $PythonExecutable -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 12) else 1)"
    return $LASTEXITCODE -eq 0
}

function Test-ModelCredentialConfiguration {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $configuredKeys = Get-Content -LiteralPath $Path | ForEach-Object {
        if ($_ -match '^\s*(DATAPILOT_LLM_API_KEY|DATAPILOT_LLM_CREDENTIALS_FILE)\s*=\s*(.+?)\s*$') {
            $matches[2].Trim().Trim('"').Trim("'")
        }
    }
    return @($configuredKeys | Where-Object { $_ -and $_ -notmatch '^(replace-with|change-me|your-)' }).Count -gt 0
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [string]$Name
    )

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*?)\s*$") {
            return $matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

Set-Location $projectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install and start Docker Desktop, then run this script again."
}

Invoke-CheckedCommand docker info

if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $environmentFile
    throw "Created .env. Add your model API settings to it, then run .\start.ps1 again."
}

if (-not (Test-ModelCredentialConfiguration -Path $environmentFile)) {
    throw "Configure DATAPILOT_LLM_API_KEY or DATAPILOT_LLM_CREDENTIALS_FILE in .env."
}

if (-not (Test-Path -LiteralPath $virtualEnvironmentPython -PathType Leaf)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $systemPython) {
        throw "Python 3.11 or 3.12 was not found. Install Python, then run this script again."
    }
    if (-not (Test-DataPilotPython -PythonExecutable $systemPython.Source)) {
        throw "DataPilot requires Python 3.11 or 3.12. The python command points to another version."
    }

    Write-Host "Creating the local DataPilot Python environment..." -ForegroundColor Cyan
    Invoke-CheckedCommand $systemPython.Source -m venv $virtualEnvironment
    Invoke-CheckedCommand $virtualEnvironmentPython -m pip install --disable-pip-version-check -e ".[postgres,data]"
}

if (-not (Test-DataPilotPython -PythonExecutable $virtualEnvironmentPython)) {
    throw "The existing .venv does not use Python 3.11 or 3.12. Remove .venv and run this script again."
}

if (-not $SkipPull) {
    Write-Host "Pulling DataPilot images..." -ForegroundColor Cyan
    Invoke-CheckedCommand docker compose -f $releaseCompose pull
}

Write-Host "Starting web, PostgreSQL, and Python runtime containers..." -ForegroundColor Cyan
Invoke-CheckedCommand docker compose -f $releaseCompose up -d --wait --wait-timeout 120

if ($LoadOlist) {
    $olistDirectory = Join-Path $projectRoot "data\raw\olist"
    if (-not (Test-Path -LiteralPath $olistDirectory -PathType Container)) {
        throw "Olist data was not found at data\raw\olist. Download the nine CSV files first."
    }

    $loaderDatabaseUrl = Get-DotEnvValue -Path $environmentFile -Name "DATAPILOT_DATA_LOADER_DATABASE_URL"
    if (-not $loaderDatabaseUrl) {
        throw "DATAPILOT_DATA_LOADER_DATABASE_URL is not configured in .env."
    }

    Write-Host "Loading the Olist dataset..." -ForegroundColor Cyan
    $previousLoaderDatabaseUrl = $env:DATAPILOT_DATA_LOADER_DATABASE_URL
    try {
        $env:DATAPILOT_DATA_LOADER_DATABASE_URL = $loaderDatabaseUrl
        Invoke-CheckedCommand $virtualEnvironmentPython scripts\load_olist.py
    }
    finally {
        $env:DATAPILOT_DATA_LOADER_DATABASE_URL = $previousLoaderDatabaseUrl
    }
}

Write-Host ""
Write-Host "DataPilot frontend: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "API documentation:  http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the backend. Containers remain running until .\stop.ps1 is used."
Write-Host ""

Invoke-CheckedCommand $virtualEnvironmentPython -m uvicorn datapilot.main:app --reload
