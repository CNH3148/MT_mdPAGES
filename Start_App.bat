@echo off
chcp 65001 >nul
title MT Exam helper - Release Version 4.0.115-2 (Portable)
REM echo ========================================================
REM echo        MT Exam helper - Release Version 4.0.115-2 (Portable)
REM echo ========================================================
REM echo.
REM echo Starting backend server...
REM echo Press Ctrl+C or close this black window to stop the server.
REM echo.
cd /d "%~dp0app"
if exist "server.exe" (
    server.exe
) else (
    echo [WARNING] server.exe not found! Falling back to server.py...
    
    REM Try to use uv if available (it auto-handles python and dependencies)
    uv --version >nul 2>&1
    if %errorlevel% equ 0 (
        uv run --with fastapi --with uvicorn --with python-multipart --with pydantic --with ruamel.yaml --with watchdog python server.py
    ) else (
        REM Try to activate the developer's conda environment if available
        call conda activate antigravity 2>nul
        python server.py
    )
    
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Failed to start server.py! 
        echo Please ensure uv or Python is installed properly with required modules ^(fastapi, uvicorn, pydantic^).
    )
)
pause
