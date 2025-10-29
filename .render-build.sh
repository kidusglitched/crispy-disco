#!/usr/bin/env bash
# Clean and rebuild environment completely to remove old Updater code
echo "🧹 Cleaning old virtual environment..."
rm -rf .venv
rm -rf ~/.cache/pip
rm -rf /opt/render/.cache/pip
rm -rf /opt/render/project/src/.venv/lib/python3.13/site-packages/telegram*

echo "📦 Installing fresh dependencies..."
pip install --upgrade pip
pip install --break-system-packages -r requirements.txt
