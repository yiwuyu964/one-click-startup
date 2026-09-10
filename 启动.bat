@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0app.py"
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0app.py"
    exit /b 0
)
python "%~dp0app.py"
