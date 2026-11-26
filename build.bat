@echo off
title Compilation de Steam Auto-Grid
echo ==================================================
echo   1. Verification des dependances...
echo ==================================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo ==================================================
echo   2. Conversion en vrai .ICO multi-tailles...
echo ==================================================
python -c "from PIL import Image; import os; src = next((f for f in ['icon.png','icon.ico'] if os.path.exists(f)), None); img = Image.open(src).convert('RGBA'); img.save('icon_win.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); print('Icone multi-tailles generee avec succes !')"

echo.
echo ==================================================
echo   3. Nettoyage et compilation PyInstaller...
echo ==================================================
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Steam-Auto-Grid.spec" del /f /q "Steam-Auto-Grid.spec"

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "Steam-Auto-Grid" ^
  --icon="icon_win.ico" ^
  --add-data "icon_win.ico;." ^
  --add-data "icon.png;." ^
  --add-data "icon.ico;." ^
  --collect-all customtkinter ^
  main.py

echo.
if exist "dist\Steam-Auto-Grid.exe" (
    ie4uinit.exe -show >nul 2>&1
    ie4uinit.exe -ClearIconCache >nul 2>&1
    echo ==================================================
    echo   Succes ! Executable pret dans dist\
    echo ==================================================
) else (
    echo ==================================================
    echo   ERREUR : La compilation a echoue.
    echo ==================================================
)
pause