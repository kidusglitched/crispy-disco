#!/usr/bin/env bash
set -o errexit

# 🧹 Clean up old pip cache (no venv)
echo "🧹 Cleaning up old pip cache..."
rm -rf ~/.cache/pip
rm -rf /opt/render/.cache/pip

# 📦 Install dependencies
echo "📦 Installing fresh dependencies..."
pip install --upgrade pip
pip install --break-system-packages -r requirements.txt

echo "✅ Build complete!"
