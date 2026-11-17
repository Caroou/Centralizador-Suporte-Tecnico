@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %errorlevel%==0 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python nao foi encontrado. Instale o Python 3.14 e marque "Add Python to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Preparando o ambiente do aplicativo...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto erro
)

echo Instalando ou atualizando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto erro
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erro

if not exist ".env" (
    echo Arquivo .env nao encontrado. Copie .env.example para .env e configure a chave de criptografia e a chave de IA.
    pause
    exit /b 1
)

echo Abrindo o Centralizador no navegador...
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
goto fim

:erro
echo.
echo Ocorreu um erro ao preparar ou iniciar o aplicativo.
pause

:fim
endlocal
