@echo off
cd /d E:\Codex\Intelligent
"D:\anaconda3\envs\env\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
