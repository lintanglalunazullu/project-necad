@echo off
title Project Necad - Stop Services
echo Menghentikan semua service Project Necad (Port 3000, 8080, 8081)...

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000 "') do (
    taskkill /F /PID %%a >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080 "') do (
    taskkill /F /PID %%a >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8081 "') do (
    taskkill /F /PID %%a >nul 2>nul
)

echo [OK] Semua service Project Necad telah dihentikan.
pause
