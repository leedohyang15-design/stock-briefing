@echo off
schtasks /delete /tn "AI Trader daily" /f
schtasks /delete /tn "AI Trader weekly" /f
schtasks /delete /tn "AI Trader US daily" /f
schtasks /delete /tn "AI Trader US weekly" /f
pause
