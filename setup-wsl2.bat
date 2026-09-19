@echo off
REM Quick launcher for WSL2 setup PowerShell script
REM Auto-elevates to Administrator if needed

setlocal enabledelayedexpansion

REM Check if running as Administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo Requesting Administrator privileges...
    echo.
    powershell -Command "Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','%~dp0setup-wsl2.ps1' -Verb runAs"
    exit /b
)

REM Run setup script
powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0setup-wsl2.ps1"
