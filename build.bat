@echo off
REM ============================================================
REM  CAMS one-click builder for Windows
REM  Makes:  installer\Output\CAMS-Setup-<version>.exe
REM  Needs:  Python 3.11 or 3.12 (python.org, tick "Add to PATH")
REM          Inno Setup 6 (jrsoftware.org) for the setup .exe
REM  Internet is needed only the first time (packages + models).
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/6] Preparing a clean Python environment...
if not exist .venv (
  python -m venv .venv || goto :nopython
)
call .venv\Scripts\activate.bat

echo [2/6] Installing packages...
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt pillow || goto :fail

echo [3/6] Getting the face AI models (once)...
python scripts\download_models.py || goto :fail

echo [4/6] Running the self-tests...
python -m pytest -q || goto :fail

echo [5/6] Building CAMS.exe...
python scripts\make_icon.py
pyinstaller installer\cams.spec --noconfirm --distpath dist --workpath build || goto :fail

for /f %%v in ('python -c "import cams;print(cams.__version__)"') do set VER=%%v

echo [6/6] Building the installer...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo.
  echo Inno Setup 6 is not installed, so only the program folder was built:
  echo   dist\CAMS\CAMS.exe
  echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php and run build.bat again
  echo to get a single CAMS-Setup.exe file.
  goto :end
)
%ISCC% /DAppVersion=%VER% installer\cams.iss || goto :fail
echo.
echo Done:  installer\Output\CAMS-Setup-%VER%.exe
goto :end

:nopython
echo Python was not found. Install Python 3.12 from python.org and tick "Add python.exe to PATH".
goto :end

:fail
echo.
echo Build failed. Read the messages above.
exit /b 1

:end
endlocal
pause
