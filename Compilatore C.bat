@echo off
echo Avvio della compilazione di Psychoscorer in corso...
echo.

C:\Users\loric\AppData\Local\Programs\Python\Python314\python.exe -m nuitka --standalone --windows-console-mode=disable --windows-icon-from-ico=icona.ico --enable-plugin=tk-inter --include-package-data=customtkinter --assume-yes-for-downloads --zig main.py

echo.
echo Compilazione completata! Controlla eventuali messaggi di errore qui sopra.
pause