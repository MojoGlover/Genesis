#!/bin/bash
# Setup script for Tablet Assistant

set -e

echo "🤖 Tablet Assistant Setup"
echo "=========================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi
echo "✅ Python 3 found"

# Check ADB
if ! command -v adb &> /dev/null; then
    echo "⚠️  ADB not found - installing via Homebrew..."
    brew install android-platform-tools
fi
echo "✅ ADB found"

# Check Ollama
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama not found"
    echo "Install from: https://ollama.ai"
    exit 1
fi
echo "✅ Ollama found"

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama not running - starting..."
    ollama serve &
    sleep 3
fi
echo "✅ Ollama running"

# Pull vision model if not present
if ! ollama list | grep -q "llava:7b"; then
    echo "📥 Pulling Ollama vision model (llava:7b)..."
    echo "⚠️  This is ~4GB and may take a few minutes..."
    ollama pull llava:7b
else
    echo "✅ Vision model (llava:7b) already installed"
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install
source venv/bin/activate
echo "📦 Installing dependencies..."
pip install -q --upgrade pip
pip install -e .

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Enable Developer Options on your tablet:"
echo "   Settings → About → Tap 'Build number' 7 times"
echo ""
echo "2. Enable USB Debugging:"
echo "   Settings → Developer Options → USB debugging"
echo ""
echo "3. For wireless connection, enable Wireless ADB:"
echo "   Settings → Developer Options → Wireless debugging"
echo ""
echo "4. Run the assistant:"
echo "   source venv/bin/activate"
echo "   python -m tablet_assistant.tablet_companion"
echo ""
