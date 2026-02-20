@echo off
cd /d "%~dp0"
python geojson_api_tool.py
if errorlevel 1 pause
