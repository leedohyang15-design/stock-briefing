@echo off
REM Scheduled US run (paper). Starts ~21:50 KST, waits for 09:00 New York, ends after 16:05 New York.
cd /d "%~dp0.."
if not exist data mkdir data
python -m src.trader.launch --market us --yes %* >> data\trader_us.log 2>&1
