@echo off
cd /d %~dp0..
streamlit run src/trader/dashboard.py %*
