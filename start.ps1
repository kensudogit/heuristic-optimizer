$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
  python -m venv (Join-Path $backend ".venv")
  & $py -m pip install -r (Join-Path $backend "requirements.txt")
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  npm install --prefix $frontend
}
if (-not (Test-Path (Join-Path $frontend ".env.local"))) {
  Copy-Item (Join-Path $frontend ".env.local.example") (Join-Path $frontend ".env.local")
}

Start-Process -WorkingDirectory $backend -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--reload","--port","8000"
Start-Process -WorkingDirectory $frontend -FilePath "npm" -ArgumentList "run","dev"
Write-Host "Backend http://localhost:8000/docs"
Write-Host "Frontend http://localhost:3000"
