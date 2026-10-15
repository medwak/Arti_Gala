@echo off
rem Start Arti Gala so phones on the same Wi-Fi (and the Android app) can connect.
call "%~dp0run.bat" --host 0.0.0.0 %*
