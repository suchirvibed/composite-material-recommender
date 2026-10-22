@echo off
rem Double-click to open the Autoclave Prepreg Study decision tool (desktop window).
rem For the text-menu version run:  py app.py
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py project_gui.py
) else (
    python project_gui.py
)
if errorlevel 1 pause
