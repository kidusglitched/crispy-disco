#!/usr/bin/env bash
set -e
python -m pip install --upgrade pip setuptools wheel
python -m pip install --prefer-binary -r requirements.txt
