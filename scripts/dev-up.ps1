<#
.SYNOPSIS
    Spins up and verifies the KeelStream local Docker Compose container environment.

.DESCRIPTION
    Provisions PostgreSQL 16, Redis 7, MinIO S3 Object Storage, Keycloak 24+ IAM,
    and optionally n8n workflow engine. Verifies container health checks before returning.

.PARAMETER WithN8n
    If specified, enables the staged n8n workflow container service.

.PARAMETER Down
    Stops and removes running containers for this stack.

.PARAMETER ResetVolumes
    Used with -Down to purge persistent volume storage (WARNING: destructive).

.PARAMETER SkipHealthCheck
    Skips the waiting loop for container health status.

.EXAMPLE
    .\scripts\dev-up.ps1
    .\scripts\dev-up.ps1 -WithN8n
    .\scripts\dev-up.ps1 -Down
#>

[CmdletBinding()]
param(
    [switch]$WithN8n,
    [switch]$Down,
    [switch]$ResetVolumes,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RootDir

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "   KeelStream Local Container Stack Provisioner     " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Handle teardown request
if ($Down) {
    Write-Host "[*] Tearing down KeelStream container stack..." -ForegroundColor Yellow
    $downArgs = @("compose", "down")
    if ($ResetVolumes) {
        $downArgs += "-v"
        Write-Host "[!] Purging persistent volumes (-v)" -ForegroundColor Red
    }
    docker @downArgs
    Write-Host "[✓] Stack stopped." -ForegroundColor Green
    return
}

# 2. Check Docker availability
try {
    $dockerVersion = docker --version
    Write-Host "[✓] Docker CLI detected: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Error "[ERROR] Docker is not installed or the Docker daemon is not running. Please start Docker Desktop."
    exit 1
}

try {
    $composeVersion = docker compose version
    Write-Host "[✓] Docker Compose detected: $composeVersion" -ForegroundColor Green
} catch {
    Write-Error "[ERROR] Docker Compose (v2) is not available. Please verify your Docker installation."
    exit 1
}

# 3. Setup .env file
$envFile = Join-Path $RootDir ".env"
$envExample = Join-Path $RootDir ".env.example"

if (-not (Test-Path $envFile)) {
    Write-Host "[!] .env not found. Copying defaults from .env.example..." -ForegroundColor Yellow
    Copy-Item -Path $envExample -Destination $envFile
    Write-Host "[✓] .env initialized successfully." -ForegroundColor Green
} else {
    Write-Host "[✓] Existing .env file found." -ForegroundColor Green
}

# 4. Ensure mount directories exist
New-Item -ItemType Directory -Force -Path (Join-Path $RootDir "scripts\init-db") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RootDir "config\keycloak") | Out-Null

# 5. Build compose arguments
$composeArgs = @("compose")
if ($WithN8n) {
    Write-Host "[*] Enabling n8n workflow orchestration profile..." -ForegroundColor Cyan
    $composeArgs += @("--profile", "workflows")
}
$composeArgs += @("up", "-d")

Write-Host "[*] Executing: docker $($composeArgs -join ' ')" -ForegroundColor Cyan
& docker @composeArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "[ERROR] docker compose up command failed with exit code $LASTEXITCODE."
    exit $LASTEXITCODE
}

# 6. Polling container health
if (-not $SkipHealthCheck) {
    Write-Host "`n[*] Polling container health status (Timeout: 90 seconds)..." -ForegroundColor Cyan
    $services = @("keelstream-postgres", "keelstream-redis", "keelstream-minio", "keelstream-keycloak")
    $maxWaitSeconds = 90

    foreach ($service in $services) {
        Write-Host -NoNewline "Waiting for $service to report healthy... "
        $elapsed = 0
        $healthy = $false

        while ($elapsed -lt $maxWaitSeconds) {
            $status = (docker inspect --format '{{json .State.Health.Status}}' $service 2>$null) -replace '"', ''
            
            if ($status -eq "healthy") {
                Write-Host "HEALTHY" -ForegroundColor Green
                $healthy = $true
                break
            } elseif ($status -eq "unhealthy") {
                Write-Host "UNHEALTHY" -ForegroundColor Red
                Write-Host "[!] Recent logs for $service:" -ForegroundColor Red
                docker logs --tail 25 $service
                Write-Error "Container $service failed health checks."
                exit 1
            }

            Start-Sleep -Seconds 3
            $elapsed += 3
            Write-Host -NoNewline "."
        }

        if (-not $healthy) {
            Write-Host "TIMEOUT (service still starting, continuing...)" -ForegroundColor Yellow
        }
    }
}

# 7. Print summary banner
Write-Host "`n====================================================" -ForegroundColor Green
Write-Host "   KeelStream Local Environment Ready!             " -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
Write-Host "Service Endpoints:"
Write-Host "  - PostgreSQL 16:  localhost:5432 (User: keelstream, DB: db_keelstream_core)"
Write-Host "  - Redis 7:        localhost:6379"
Write-Host "  - MinIO S3 API:   http://localhost:9000 (Access: minioadmin / minioadmin)"
Write-Host "  - MinIO Console:  http://localhost:9001"
Write-Host "  - Keycloak IAM:   http://localhost:8080 (Admin: admin / admin)"
if ($WithN8n) {
    Write-Host "  - n8n Workflows:  http://localhost:5678"
}
Write-Host "----------------------------------------------------"
Write-Host "To view live logs:   docker compose logs -f"
Write-Host "To stop containers:  .\scripts\dev-up.ps1 -Down"
Write-Host "====================================================`n"
