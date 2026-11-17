# Script de preparação do ambiente (Windows / PowerShell)
# Uso:  .\scripts\setup.ps1
#
# Cria o ambiente virtual, instala dependências e executa os testes.

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

Write-Host "==> Preparando ambiente em $raiz" -ForegroundColor Cyan

if (-not (Test-Path "venv")) {
    Write-Host "==> Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv venv
}

$python = Join-Path $raiz "venv\Scripts\python.exe"

Write-Host "==> Atualizando pip..." -ForegroundColor Yellow
& $python -m pip install --quiet --upgrade pip

Write-Host "==> Instalando dependências de desenvolvimento..." -ForegroundColor Yellow
& $python -m pip install --quiet -r requirements-dev.txt

Write-Host "==> Executando testes..." -ForegroundColor Yellow
& $python -m pytest

Write-Host "==> Ambiente pronto. Para subir a API:" -ForegroundColor Green
Write-Host "    .\venv\Scripts\uvicorn.exe main:app --reload" -ForegroundColor Green
