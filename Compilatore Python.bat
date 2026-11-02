@echo off
cd /d "%~dp0"
echo Installazione strumenti di compilazione e dipendenze in corso...
"C:\Users\loric\AppData\Local\Programs\Python\Python314\python.exe" -m pip install pyinstaller customtkinter matplotlib reportlab scipy

echo.
echo Compilazione in corso... Generazione CARTELLA di PsychoScorer...
echo (Questo processo puo' richiedere alcuni minuti, non chiudere la finestra)

"C:\Users\loric\AppData\Local\Programs\Python\Python314\python.exe" -m PyInstaller --noconsole --icon=icona.ico --name=PsychoScorer main.py

echo.
echo Compilazione terminata con successo!
echo Troverai la cartella pronta all'uso in: dist\PsychoScorer
pause