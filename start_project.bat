
@echo off
title Cloud-Based Notification System

cd /d "%~dp0"

echo Starting Redis Server...
start "Redis Server" cmd /k "venv\Scripts\python.exe redis_dev_server.py"

timeout /t 3 /nobreak >nul

echo Starting Notification Worker...
start "Notification Worker" cmd /k "venv\Scripts\python.exe worker.py"

timeout /t 2 /nobreak >nul

echo Starting Flask Application...
start "Flask Application" cmd /k "venv\Scripts\python.exe app.py"

timeout /t 3 /nobreak >nul

start "" "http://127.0.0.1:5000"

echo All services have been started.
pause
