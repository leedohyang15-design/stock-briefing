@echo off
REM Saturday weekly review: report + proposal to Telegram, waits for /apply
cd /d "%~dp0.."
if not exist data mkdir data
python -m src.trader.run_weekly %* >> data\weekly.log 2>&1
