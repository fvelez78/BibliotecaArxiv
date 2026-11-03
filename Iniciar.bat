@echo off
chcp 65001 >nul
title Biblioteca arXiv
cd /d "%~dp0"

rem --- 1. Buscar Python ---
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo No se encontro Python. Instalalo desde https://www.python.org
        echo y marca la casilla "Add python.exe to PATH".
        pause
        exit /b 1
    )
    set "PY=py"
)

rem --- 2. Instalar componentes la primera vez (PySide6 y PyMuPDF) ---
%PY% -c "import PySide6, pymupdf" >nul 2>nul
if errorlevel 1 (
    echo Instalando componentes de la aplicacion. Solo pasa la primera vez, puede tardar unos minutos...
    %PY% -m pip install --upgrade PySide6 pymupdf
    if errorlevel 1 (
        echo.
        echo No se pudieron instalar los componentes. Revisa tu conexion a internet.
        pause
        exit /b 1
    )
)

rem --- 3. Abrir la app sin dejar la consola abierta ---
if /i "%PY%"=="python" (
    where pythonw >nul 2>nul
    if not errorlevel 1 (
        start "" pythonw "%~dp0app.py"
        exit /b 0
    )
)
start "" %PY% "%~dp0app.py"
exit /b 0
