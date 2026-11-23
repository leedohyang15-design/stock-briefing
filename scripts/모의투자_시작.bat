@echo off
cd /d "%~dp0.."
title AI Trader - PAPER
python -m src.trader.launch %*
if errorlevel 9009 py -m src.trader.launch %*
