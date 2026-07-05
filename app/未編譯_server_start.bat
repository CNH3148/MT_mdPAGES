@echo off
cd /d "%~dp0"
echo =========================================
echo   Start MT Exam Prep (Uncompiled Version)
echo =========================================
echo.
echo Starting server...
echo (Please do not close this black window)
echo.

set "UV_PATH=C:\Users\star0\.local\bin\uv.exe"
IF EXIST "%UV_PATH%" GOTO RUN_UV

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 GOTO ERROR_PYTHON

python -c "import fastapi, uvicorn, multipart, pydantic" 2>nul
IF %ERRORLEVEL% NEQ 0 GOTO INSTALL_PIP

:RUN_SERVER
python server.py
pause
exit /b

:RUN_UV
"%UV_PATH%" run --with fastapi --with uvicorn --with python-multipart --with pydantic python server.py
pause
exit /b

:INSTALL_PIP
echo Installing required packages...
python -m pip install fastapi uvicorn python-multipart pydantic --break-system-packages
echo Done!
echo.
GOTO RUN_SERVER

:ERROR_PYTHON
echo [Error] Python or uv not found!
echo Please install Python and ensure it is in PATH.
pause
exit /b
