@echo off
setlocal

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

echo ============================================================
echo  py-analysis-tool - full Windows bootstrap
echo ============================================================

where python >nul 2>&1 || (echo [!] python not in PATH & exit /b 1)
where git    >nul 2>&1 || (echo [!] git not in PATH & exit /b 1)
where cmake  >nul 2>&1 || (echo [!] cmake not in PATH - install CMake & exit /b 1)

if not exist ".venv" (
    echo [*] creating virtualenv...
    python -m venv .venv
    if errorlevel 1 (echo [!] venv creation failed & exit /b 1)
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
echo [*] installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (echo [!] pip install failed & exit /b 1)

echo [*] building pycdc...
call "%REPO_ROOT%scripts\build_pycdc.bat"
if errorlevel 1 (
    echo [!] pycdc build failed - tool will fall back to uncompyle6/dis
) else (
    echo [+] pycdc ready
)

echo [*] smoke test...
python -m py_analysis_tool.main --version
if errorlevel 1 (echo [!] smoke test failed & exit /b 1)

echo.
echo ============================================================
echo  Done.
echo  Activate env : .venv\Scripts\activate
echo  Run tool     : python -m py_analysis_tool.main ^<input^> -o out
echo ============================================================
endlocal