@echo off
title 3Dosim v4 Launcher
setlocal enabledelayedexpansion

:: ── Paths ──
set "V4_ROOT=C:\programas\3Dosim\3Dosim_v4"
set "LAUNCHER=%V4_ROOT%\launcher\app.py"

:: ── Colores ──
set "CYAN=[96m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "RESET=[0m"

echo.
echo %CYAN%============================================%RESET%
echo %CYAN%  3Dosim v4 — Dosimetria 3D para MN%RESET%
echo %CYAN%============================================%RESET%
echo.
echo  Directorio: %V4_ROOT%
echo.

:: ── 1. Verificar Python ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo %RED%[ERROR] Python no encontrado en PATH.%RESET%
    echo        Instale Python 3.10+ desde python.org
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo %GREEN%[OK] Python %PYVER%%RESET%

:: ── 2. Verificar PyQt5 ──
python -c "import PyQt5" >nul 2>&1
if %errorlevel% neq 0 (
    echo %YELLOW%[WARN] PyQt5 no instalado. Instalando...%RESET%
    pip install PyQt5
    if !errorlevel! neq 0 (
        echo %RED%[ERROR] No se pudo instalar PyQt5.%RESET%
        pause
        exit /b 1
    )
    echo %GREEN%[OK] PyQt5 instalado%RESET%
) else (
    echo %GREEN%[OK] PyQt5 instalado%RESET%
)

:: ── 3. Verificar .env ──
if not exist "%V4_ROOT%\.env" (
    if exist "%V4_ROOT%\.env.template" (
        echo %YELLOW%[WARN] .env no encontrado.%RESET%
        echo        Copie .env.template como .env y configure su API key
        echo        para habilitar el AI Supervisor.
        echo.
    )
)

:: ── 4. Verificar launcher ──
if not exist "%LAUNCHER%" (
    echo %RED%[ERROR] No encontrado: %LAUNCHER%%RESET%
    pause
    exit /b 1
)
echo %GREEN%[OK] Launcher encontrado%RESET%

:: ── 5. Lanzar ──
echo.
echo %GREEN%Iniciando launcher...%RESET%
echo.

:: Redirigir stderr a un log para debug
set "ERRLOG=%V4_ROOT%\launcher\error.log"
python "%LAUNCHER%" 2>>"%ERRLOG%"

if exist "%ERRLOG%" (
    for %%F in ("%ERRLOG%") do if %%~zF gtr 0 (
        echo %RED%[ERROR] Se detectaron errores. Revise: %ERRLOG%%RESET%
    )
)

echo.
echo %CYAN%Launcher cerrado.%RESET%
echo.
timeout /t 3 /nobreak >nul
