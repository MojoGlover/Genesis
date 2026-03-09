# Tablet Assistant

AI-powered overlay assistant for Android tablets using Ollama vision models.

## Features
- 📸 Real-time screenshot analysis
- 🤖 Vision-based UI understanding (Ollama llava)
- 🎯 Contextual help and suggestions
- 📝 Visual annotations and overlays

## Setup
1. Enable Developer Options on tablet (Settings → About → Tap "Build number" 7 times)
2. Enable USB Debugging (Settings → Developer Options → USB debugging)
3. Enable Wireless ADB (Settings → Developer Options → Wireless debugging)
4. Connect tablet to same WiFi network as computer

## Usage
```bash
# Install dependencies
pip install -e .

# Start assistant
python tablet_companion.py --tablet-ip 192.168.1.XXX
```

## Architecture
- **ADB Bridge**: Screenshot capture via wireless ADB
- **Vision Assistant**: Ollama vision model analysis
- **Overlay Generator**: Visual annotations (boxes, arrows, labels)
- **WebSocket Server**: Real-time tablet communication
