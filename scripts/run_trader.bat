@echo off
REM Scheduled weekday run (paper trading by default). Add --live --yes for real account.
cd /d "%~dp0.."
if not exist data mkdir data
python -m src.trader.launch --yes %* >> data\trader.log 2>&1
