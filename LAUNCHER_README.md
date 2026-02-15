# Engineer0 Launcher

One-command startup for Engineer0 with automatic browser launch and restart functionality.

## 🚀 Quick Start

```bash
./launcher.sh
```

That's it! The launcher will:
1. ✅ Check/create virtual environment
2. ✅ Start Ollama (if not running)
3. ✅ Launch Engineer0 dashboard
4. ✅ Open browser automatically
5. ✅ Show system status

## 📋 Commands

```bash
./launcher.sh start    # Start Engineer0 (default)
./launcher.sh stop     # Stop all services
./launcher.sh restart  # Restart everything
./launcher.sh status   # Check if running
./launcher.sh logs     # View dashboard logs
```

## 🔄 In-Dashboard Restart

The dashboard includes a **"Restart System"** button with detailed progress:

### How it works:

1. **Click "Restart System"** button in the top-right
2. **Confirm** the restart action
3. **Watch real-time progress**:
   - 🛑 Stopping current services
   - 🔄 Killing dashboard process
   - 🧹 Cleaning up resources
   - 🔍 Checking Ollama status
   - 🚀 Starting Ollama
   - ✅ Ollama running
   - 📦 Activating virtual environment
   - 🌐 Starting dashboard server
   - ⏳ Waiting for dashboard
   - ✅ Dashboard ready
   - 🎉 Restart complete!

4. **Click "Ready - Click to Reload UI"** when the green button appears
5. **Dashboard reloads** automatically with fresh state

### Features:
- ✅ Real-time progress bar
- ✅ Detailed step-by-step status
- ✅ Visual indicators for each step
- ✅ Safe cancellation before completion
- ✅ Automatic UI reload when ready

## 📊 Dashboard Features

### Status Cards
- **System Status** - Current state (Running/Stopped)
- **Tasks Completed** - Total tasks processed
- **Uptime** - How long the system has been running
- **Memory Usage** - Current memory consumption

### Controls
- **Restart System** - Restart with progress tracking
- **Stop** - Gracefully stop all services
- **Real-time Metrics** - CPU/Memory graphs

## 🛠️ Requirements

- Python 3.10+
- Ollama installed
- Bash shell (macOS/Linux)

## 📁 File Structure

```
~/ai/GENESIS/
├── launcher.sh                    # Main launcher script
├── core/monitoring/
│   └── dashboard_v2.py           # Enhanced dashboard with restart
└── logs/
    ├── dashboard.log             # Dashboard logs
    ├── dashboard.pid             # Dashboard process ID
    ├── ollama.log                # Ollama logs
    └── restart_status.txt        # Restart progress tracking
```

## 🔧 Troubleshooting

### Launcher won't start
```bash
# Make executable
chmod +x launcher.sh

# Check Python version
python3 --version  # Should be 3.10+

# Check Ollama
ollama list
```

### Dashboard won't load
```bash
# Check logs
./launcher.sh logs

# Check if port 8050 is available
lsof -i :8050

# Restart
./launcher.sh restart
```

### Ollama issues
```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# Restart Ollama
pkill ollama
ollama serve
```

### Restart button not working
```bash
# Check launcher script exists
ls -la launcher.sh

# Ensure it's executable
chmod +x launcher.sh

# Check logs for errors
tail -f logs/dashboard.log
```

## 🎯 Use Cases

### Development
```bash
# Start for development
./launcher.sh

# Make code changes
# ...

# Restart from dashboard (click Restart button)
# Watch progress, click reload when ready
```

### Production
```bash
# Start in background
nohup ./launcher.sh > /dev/null 2>&1 &

# Check status
./launcher.sh status

# View logs
./launcher.sh logs
```

### Quick Restart After Updates
1. Pull latest code: `git pull`
2. Open dashboard: http://localhost:8050
3. Click **"Restart System"**
4. Watch progress automatically
5. Click **"Ready - Click to Reload UI"** when green
6. Dashboard refreshes with new code

## 🔒 Security

The launcher:
- ✅ Runs in user space (no sudo required)
- ✅ Uses virtual environment for isolation
- ✅ Logs all activity
- ✅ Graceful shutdown on Ctrl+C
- ✅ Safe restart with confirmation

## 📝 Notes

- Dashboard runs on port **8050**
- Ollama runs on port **11434**
- Logs stored in `~/ai/GENESIS/logs/`
- Virtual environment in `~/ai/GENESIS/venv/`

## 🆘 Support

If you encounter issues:

1. Check logs: `./launcher.sh logs`
2. Check status: `./launcher.sh status`
3. Try restart: `./launcher.sh restart`
4. Check Ollama: `ollama list`
5. Recreate venv: `rm -rf venv && ./launcher.sh`

---

**Engineer0** - Autonomous AI Agent with One-Click Launch & Restart 🚀
