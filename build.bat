@echo off
echo Installation des dependances...
python -m pip install -r requirements.txt
echo.
echo Compilation de Steam-Auto-Grid.exe...
python -m PyInstaller --noconfirm --onefile --windowed --name "Steam-Auto-Grid" --collect-all customtkinter main.py
echo.
if exist "dist\Steam-Auto-Grid.exe" (
    echo [OK] Compilation terminee ! L'executable est dans : dist\Steam-Auto-Grid.exe
) else (
    echo [ERREUR] La compilation a echoue. Verifie les messages ci-dessus.
)
pause
