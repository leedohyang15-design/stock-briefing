@echo off
cd /d "%~dp0.."
title AI Trader - US PAPER
python -m src.trader.launch --market us %*
if errorlevel 9009 py -m src.trader.launch --market us %*
