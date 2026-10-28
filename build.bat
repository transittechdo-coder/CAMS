@echo off
REM ============================================================
REM  CAMS one-click builder for Windows
REM
REM  Double-click this file. It builds CAMS, installs it on this
REM  PC, puts the CAMS icon on your desktop and opens CAMS.
REM  After that you never need this file again: just double-click
REM  the CAMS icon on the desktop.
REM
REM  Needs:  Python 3.11 or 3.12 (python.org, tick "Add to PATH")
REM          Inno Setup 6 (jrsoftware.org) to make CAMS-Setup.exe
REM          (without it, CAMS still gets a desktop icon)
REM  Internet is needed only for the first build.
REM ============================================================
setlocal
cd /d "%~dp0"
title Building CAMS

echo.
echo [1/7] Preparing a clean Python environment...
if not exist .venv (
  python -m venv .venv || goto :nopython
)
call .venv\Scripts\activate.bat

echo [2/7] Installing packages...
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt pillow || goto :fail

echo [3/7] Getting the AI models (once)...
python scripts\download_models.py || goto :fail

echo [4/7] Running the self-tests...
python -m pytest -q || goto :fail

echo [5/7] Building CAMS.exe...
taskkill /IM CAMS.exe /F >nul 2>&1
python scripts\make_icon.py
pyinstaller installer\cams.spec --noconfirm --distpath dist --workpath build || goto :fail

for /f %%v in ('python -c "import cams;print(cams.__version__)"') do set VER=%%v

echo [6/7] Building the installer...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% goto :noinno
%ISCC% /Q /DAppVersion=%VER% installer\cams.iss || goto :fail
set SETUP=installer\Output\CAMS-Setup-%VER%.exe

echo [7/7] Installing CAMS on this PC and opening it...
"%SETUP%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER || goto :fail
set APP=%LOCALAPPDATA%\Programs\CAMS\CAMS.exe
if not exist "%APP%" goto :fail
start "" "%APP%"
echo.
echo ============================================================
echo  CAMS is installed and opening now.
echo  From now on, just double-click the CAMS icon on your desktop.
echo  To give CAMS to another PC, copy this one file:
echo    %CD%\%SETUP%
echo ============================================================
goto :done

:noinno
echo.
echo Inno Setup 6 is not installed, so no CAMS-Setup.exe was made.
echo [7/7] Putting a CAMS icon on your desktop and opening CAMS...
set APP=%CD%\dist\CAMS\CAMS.exe
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\CAMS.lnk');" ^
  "$s.TargetPath='%APP%'; $s.WorkingDirectory='%CD%\dist\CAMS'; $s.IconLocation='%APP%,0'; $s.Description='Camera AI Management System'; $s.Save()"
start "" "%APP%"
echo.
echo ============================================================
echo  CAMS is opening now, and there is a CAMS icon on your desktop.
echo  (It runs from this folder: %CD%\dist\CAMS - do not delete it.)
echo  To make a CAMS-Setup.exe for other PCs, install Inno Setup 6
echo  from https://jrsoftware.org/isdl.php and run build.bat again.
echo ============================================================
goto :done

:nopython
echo.
echo Python was not found. Install Python 3.12 from python.org and tick
echo "Add python.exe to PATH", then run build.bat again.
goto :end

:fail
echo.
echo Build failed. Read the messages above.
goto :end

:done
endlocal
if not defined CI timeout /t 15
exit /b 0

:end
endlocal
if not defined CI pause
exit /b 1
