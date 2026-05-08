# Tools Library
All tools shared across BlackZero agents live here.
Each tool follows the BaseTool interface from agent/tools/base.py

To add a tool:
1. Create a file in the appropriate subfolder
2. Subclass BaseTool
3. Implement name, description, run()
4. Register it in the agent's config.yaml

Subfolders:
- dev/   — code execution, file ops, git
- data/  — web search, document reading, APIs
- system/ — shell, process management
