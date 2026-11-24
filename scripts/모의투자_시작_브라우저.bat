@echo off
REM Same as paper start, but always opens the screen in your web browser (use if the app window is blank)
cd /d "%~dp0.."
title AI Trader - PAPER (browser)
python -m src.trader.launch --browser %*
if errorlevel 9009 py -m src.trader.launch --browser %*
