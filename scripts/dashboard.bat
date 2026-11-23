@echo off
cd /d "%~dp0.."
python -m src.trader.web.server %*
if errorlevel 9009 py -m src.trader.web.server %*
