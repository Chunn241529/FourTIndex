@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "MODELS_DIR=D:\LMStudio\models\trung"
set "HF_USER=trungvn2401s"

for /f "delims=#" %%A in ('"prompt #$E# & for %%B in (1) do rem"') do set "ESC=%%A"
set "RESET=%ESC%[0m"
set "BOLD=%ESC%[1m"
set "CYAN=%ESC%[96m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"

where hf >nul 2>&1 || (
    echo %YELLOW%[CANH BAO] Khong tim thay lenh hf.%RESET%
    echo Dang cai dat thong qua pip...
    pip install -U "huggingface_hub[cli]" || (
        echo [LOI] Cai dat that bai. Vui long cai dat thu cong.
        exit /b 1
    )
)

if "%~1"=="" goto menu
if /i "%~1"=="login" goto login
if /i "%~1"=="upload" goto upload
goto help

:menu
echo.
echo %CYAN%============================================%RESET%
echo %BOLD%    HUGGING FACE MODEL UPLOADER%RESET%
echo %CYAN%============================================%RESET%
echo 1. Dang nhap Hugging Face (Login)
echo 2. Upload Model tu LMStudio (D:\LMStudio\models\trung)
echo 3. Thoat
echo.
set /p choice="Chon (1/2/3): "
if "%choice%"=="1" goto login
if "%choice%"=="2" goto upload
exit /b 0

:login
echo.
echo %CYAN%[LOGIN] Dang mo trinh dang nhap Hugging Face...%RESET%
hf auth login
exit /b %errorlevel%

:upload
echo.
if not exist "%MODELS_DIR%" (
    echo [LOI] Thu muc "%MODELS_DIR%" khong ton tai.
    exit /b 1
)

echo %CYAN%[UPLOAD] Danh sach model hien co trong "%MODELS_DIR%":%RESET%
set "count=0"
for /d %%D in ("%MODELS_DIR%\*") do (
    set /a count+=1
    setlocal EnableDelayedExpansion
    echo - %%~nxD
    endlocal
)

if %count%==0 (
    echo [CANH BAO] Khong tim thay thu muc model nao.
    exit /b 0
)

echo.
set /p "folder_name=Nhap ten thu muc model can upload: "
if not defined folder_name exit /b 1

set "TARGET_FOLDER=%MODELS_DIR%\%folder_name%"
if not exist "%TARGET_FOLDER%" (
    echo [LOI] Thu muc "%TARGET_FOLDER%" khong ton tai.
    exit /b 1
)

set "REPO_ID=%HF_USER%/%folder_name%"
echo.
echo %YELLOW%Dang upload:%RESET% "%TARGET_FOLDER%"
echo %YELLOW%Len HF Repo:%RESET% https://huggingface.co/%REPO_ID%
echo.
set /p confirm="Ban chac chan muon tiep tuc? (y/N): "
if /i not "%confirm%"=="y" exit /b 0

hf upload "%REPO_ID%" "%TARGET_FOLDER%" . --repo-type model
if errorlevel 1 (
    echo [LOI] Qua trinh upload that bai.
    exit /b 1
)

echo.
echo %GREEN%[OK] Upload thanh cong len https://huggingface.co/%REPO_ID%%RESET%
exit /b 0

:help
echo Lenh ho tro:
echo   hf.bat login   - Dang nhap Hugging Face
echo   hf.bat upload  - Tai model len HF
exit /b 0
