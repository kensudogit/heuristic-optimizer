$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:COMPOSE_BAKE = "false"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Error "Docker が見つかりません。Docker Desktop を起動してから再実行してください。"
}

docker compose up --build -d
Write-Host "Backend  http://localhost:8010/docs"
Write-Host "Frontend http://localhost:3010"
Write-Host "cmd からは start.cmd を実行してください。"
