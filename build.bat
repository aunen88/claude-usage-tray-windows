@echo off
setlocal

echo Installing / upgrading build dependencies...
pip install --upgrade pyinstaller pystray Pillow requests

echo.
echo Building ClaudeUsageTray.exe ...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name ClaudeUsageTray ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL._imaging ^
    --hidden-import PIL.ImageFont ^
    --hidden-import PIL.ImageDraw ^
    --collect-all pystray ^
    main.py

echo.
if exist dist\ClaudeUsageTray.exe (
    echo Build succeeded: dist\ClaudeUsageTray.exe
) else (
    echo Build FAILED – check output above.
)

endlocal
pause
