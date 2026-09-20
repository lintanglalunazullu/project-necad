@echo off
setlocal enabledelayedexpansion
title Project Necad - Dev Launcher

echo ========================================================
echo    Project Necad - SMPN 2 Cibungbulang - Windows Dev
echo ========================================================
echo.

:: 1. Cek Python
where python >nul 2>nul
if %errorlevel% equ 0 goto python_ok
echo [ERROR] Python tidak terdeteksi!
echo Silakan install Python versi 3.10 - 3.12 dari https://www.python.org
echo PENTING: Saat instalasi di Windows, CENTANG kotak "Add Python to PATH".
echo.
pause
exit /b 1

:python_ok
:: 2. Setup path direktori
set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "API_DIR=%ROOT_DIR%\services\api"
set "VENV_DIR=%API_DIR%\.venv"

:: 3. Cek file .env backend
if exist "%API_DIR%\.env" goto env_ok
if not exist "%API_DIR%\.env.example" goto env_ok
echo [INFO] Menyalin services\api\.env.example ke .env...
copy "%API_DIR%\.env.example" "%API_DIR%\.env" >nul
echo [PERHATIAN] File services\api\.env telah dibuat dari .env.example.

:env_ok
:: 4. Buat Virtual Environment (.venv) jika belum ada
if exist "%VENV_DIR%\Scripts\activate.bat" goto venv_ready

echo [INFO] Membuat virtual environment Python di services\api\.venv...
python -m venv "%VENV_DIR%"
if %errorlevel% neq 0 (
    echo [ERROR] Gagal membuat virtual environment. Pastikan Python terinstall dengan benar.
    pause
    exit /b 1
)
echo [INFO] Berhasil membuat .venv.
echo [INFO] Menginstall dependensi requirements.txt (proses ini butuh 1-2 menit)...
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --quiet --upgrade pip
pip install -r "%API_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Gagal menginstall dependensi requirements.txt.
    pause
    exit /b 1
)
echo [OK] Semua dependensi Python berhasil diinstall!

:venv_ready
echo.
echo ========================================================
echo [OK] Menjalankan semua service di jendela terpisah...
echo ========================================================
echo 1. Backend API        -^> http://localhost:3000 (Swagger: /docs)
echo 2. Website Sekolah    -^> http://localhost:8080
echo 3. Portal AI Mentor   -^> http://localhost:8081
echo ========================================================
echo.

:: 5. Jalankan Service di 3 jendela Command Prompt terpisah
start "Project Necad - 1. Backend API (Port 3000)" cmd /k "cd /d "%API_DIR%" && call "%VENV_DIR%\Scripts\activate.bat" && uvicorn app:app --host 0.0.0.0 --port 3000 --reload"

start "Project Necad - 2. Website Sekolah (Port 8080)" cmd /k "cd /d "%ROOT_DIR%\apps\school-web" && python -m http.server 8080"

start "Project Necad - 3. Portal Mentor (Port 8081)" cmd /k "cd /d "%ROOT_DIR%\apps\mentor-web" && python -m http.server 8081"

echo Semua service sudah berjalan di 3 jendela terminal.
echo Untuk menghentikan semua service, cukup jalankan stop.bat atau tutup jendela terminal.
echo.
pause
