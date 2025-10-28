#!/usr/bin/env bash
set -e
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
rm -rf /opt/render/project/src/.venv/lib/python3.13/site-packages/telegram*
python3 main.py
