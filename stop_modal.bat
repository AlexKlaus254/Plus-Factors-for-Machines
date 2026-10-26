@echo off
rem Stops the Modal endpoints used by this project and logs what is still running.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore
echo ==== %date% %time% ==== >> stop_modal_log.txt
py -m modal endpoint stop qwen -y >> stop_modal_log.txt 2>&1
py -m modal endpoint stop gemma4 -y >> stop_modal_log.txt 2>&1
py -m modal endpoint list >> stop_modal_log.txt 2>&1
py -m modal app list >> stop_modal_log.txt 2>&1
type stop_modal_log.txt
