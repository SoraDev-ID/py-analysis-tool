@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM build_pycdc.bat - Clone + build pycdc (Decompyle++) on Windows
REM Requires: git, cmake (>=3.15), Visual Studio 2019/2022 C++ tools
REM ============================================================

set "REPO_ROOT=%~dp0.."
set "PYCDC_DIR=%REPO_ROOT%\third_party\pycdc"

echo [*] Repo root: %REPO_ROOT%
echo [*] pycdc target: %PYCDC_DIR%

where git >nul 2>&1 || (echo [!] git not found in PATH & exit /b 1)
where cmake >nul 2>&1 || (echo [!] cmake not found in PATH & exit /b 1)

if not exist "%REPO_ROOT%\third_party" mkdir "%REPO_ROOT%\third_party"

if exist "%PYCDC_DIR%\.git" (
    echo [*] pycdc already cloned, pulling latest...
    pushd "%PYCDC_DIR%"
    git pull --ff-only
    popd
) else (
    echo [*] cloning pycdc...
    git clone --depth 1 https://github.com/zrax/pycdc.git "%PYCDC_DIR%"
    if errorlevel 1 (echo [!] clone failed & exit /b 1)
)

echo [*] configuring cmake...
cmake -S "%PYCDC_DIR%" -B "%PYCDC_DIR%\build" -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 (echo [!] cmake configure failed & exit /b 1)

echo [*] building (Release)...
cmake --build "%PYCDC_DIR%\build" --config Release
if errorlevel 1 (echo [!] build failed & exit /b 1)

set "BUILT="
for %%F in (
    "%PYCDC_DIR%\build\pycdc.exe"
    "%PYCDC_DIR%\build\Release\pycdc.exe"
    "%PYCDC_DIR%\pycdc.exe"
) do (
    if exist "%%~F" (
        set "BUILT=%%~F"
        goto :found
    )
)

:found
if defined BUILT (
    echo [+] pycdc built: %BUILT%
) else (
    echo [!] built but pycdc.exe not located; check %PYCDC_DIR%\build
    exit /b 1
)

endlocal