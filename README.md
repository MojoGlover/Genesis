# GENESIS - Module Development Lab

**GENESIS is the build/test/install pipeline for all AI modules.**

## Workflow

```
Build in GENESIS → Test in GENESIS → Install system-wide → Use anywhere
```

## Module Registry

| Module | Status | Description |
|--------|--------|-------------|
| `ai_starter` | ✅ Installed | Base template (Pydantic, RAG, MCP, LangChain, LangGraph) |
| `rasa_module` | ✅ Installed | Conversational AI (Ollama-based) |
| `vision_engine` | 🔧 Ready to install | Universal vision AI (Ollama llava) |
| `tablet_assistant` | 🔧 Ready to install | Android tablet overlay AI |

## Standard Dev Workflow

### 1. Build
```bash
cd ~/ai/GENESIS/<module_name>
# Write code...
```

### 2. Test
```bash
cd ~/ai/GENESIS/<module_name>
python -m pytest tests/ -v
# or: python -c "import <module>; ..."
```

### 3. Install
```bash
# Install into Engineer0
cd ~/ai/Engineer0
source venv/bin/activate
pip install -e ~/ai/GENESIS/<module_name>

# Install into PlugOps
cd ~/ai/PlugOps
source venv/bin/activate
pip install -e ~/ai/GENESIS/<module_name>

# Install system-wide (available to all projects)
pip install -e ~/ai/GENESIS/<module_name>
```

## Installing All Modules

Run the master install script:
```bash
~/ai/GENESIS/install_all.sh
```

## Directory Structure
```
~/ai/GENESIS/
├── README.md              ← This file
├── install_all.sh         ← Master install script
├── ai_starter/            ← Base template module
├── rasa_module/           ← Conversational AI
├── vision_engine/         ← Vision AI (NEW)
└── tablet_assistant/      ← Tablet overlay AI (NEW)
```

## Browser-only backup download (no commands)

If you are viewing this repository in a browser file list, download this file in the top-level `Genesis` folder:

`DOWNLOAD_THIS_FROM_BROWSER_20260307_010547.zip`

If you do not see it, refresh the browser file list and sort by newest files.

If you see buttons like **Diff**, **Logs**, **Unarchive**, **Share**, and **Create PR**, you are already in the correct browser view; scroll the file list and click the ZIP filename directly.


## Windows troubleshooting for "dir *.zip" (no files shown)

If Command Prompt shows `File Not Found` when you run `dir *.zip`, open:

`WINDOWS_ZIP_TROUBLESHOOTING.md`

It includes exact commands to check Downloads/OneDrive folders, search your full user profile, and copy the export ZIP to `C:\` or `D:\`.
