@echo off
echo ==========================================
echo Building FourTIndex Distribution Package
echo ==========================================

:: Detect python executable
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo Using virtual environment Python: .venv\Scripts\python.exe
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo Error: Python is not installed or not in PATH.
        pause
        exit /b 1
    )
)

:: Install/Upgrade the 'build' package
echo Upgrading build package...
%PYTHON_EXE% -m pip install --upgrade build setuptools wheel

:: Clean old builds
if exist dist (
    echo Cleaning old build files...
    rmdir /s /q dist
)
if exist build (
    echo Cleaning temp build files...
    rmdir /s /q build
)
if exist fourtindex.egg-info (
    echo Cleaning egg-info...
    rmdir /s /q fourtindex.egg-info
)

:: Bump version
echo Auto-bumping version in setup.py...
%PYTHON_EXE% bump_version.py

:: Run build
echo Running %PYTHON_EXE% -m build...
%PYTHON_EXE% -m build

:: Install updated version
echo.
echo Installing updated version...
%PYTHON_EXE% -m pip install -U .

echo.
echo ==========================================
echo Build completed! Files are in dist/
echo ==========================================
pause
