@echo off
echo ==========================================
echo Building FourTIndex Distribution Package
echo ==========================================

:: Check if python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Install/Upgrade the 'build' package
echo Upgrading build package...
python -m pip install --upgrade build setuptools wheel

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
python bump_version.py

:: Run build
echo Running python -m build...
python -m build

:: Install globally
echo.
echo Installing updated version globally...
python -m pip install -U .

echo.
echo ==========================================
echo Build completed! Files are in dist/
echo ==========================================
pause
