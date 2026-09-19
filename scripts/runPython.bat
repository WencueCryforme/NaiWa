@echo off
rem Windows entry point for the scripts in this folder.
rem All arguments are forwarded to the interpreter configured below.
rem Usage: runPython.bat <script> [args...]
rem Example: runPython.bat img_resize.py -o .output -R
rem Set PYTHON to the interpreter that has opencv-python installed.
set "PYTHON=python"

if "%~1"=="" (
    echo Usage: runPython.bat ^<script^> [args...]
    echo Example: runPython.bat img_resize.py -o .output -R
    pause
    exit /b 1
)

rem Dependency guard: the scripts need opencv-python 4.11 or newer.
"%PYTHON%" -c "import cv2" 1>nul 2>nul
if errorlevel 1 (
    echo [ERROR] opencv-python is not available for: %PYTHON%
    echo Install it first, for example:
    echo     python -m pip install --upgrade opencv-python
    pause
    exit /b 1
)

"%PYTHON%" %*
echo.
echo Exit code: %ERRORLEVEL%
pause
