@echo off
cd /d "%~dp0.."
title AI Trader - LIVE
python -m src.trader.launch --live %*
if errorlevel 9009 py -m src.trader.launch --live %*
