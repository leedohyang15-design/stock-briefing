@echo off
schtasks /delete /tn "AI Trader daily" /f
schtasks /delete /tn "AI Trader weekly" /f
pause
