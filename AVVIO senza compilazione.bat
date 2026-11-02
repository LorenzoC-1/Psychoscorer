@echo off
cd /d "%~dp0"
echo Installazione dipendenze in corso...
"C:\Users\loric\AppData\Local\Programs\Python\Python314\python.exe" -m pip install customtkinter matplotlib reportlab scipy
echo.
echo Avvio PsychoScorer...
py main.py
pause