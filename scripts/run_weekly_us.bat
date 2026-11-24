@echo off
cd /d "%~dp0.."
if not exist data mkdir data
python -m src.trader.run_weekly --market us %* >> data\weekly_us.log 2>&1
