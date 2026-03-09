"""
File Operations Tool
Read, write, and manage files
"""
import os
from pathlib import Path
from typing import List, Optional


ALLOWED_DIRS = ["./data/uploads", "./data/cache"]


def read_file(filepath: str) -> str:
    """Read content from a file"""
    path = Path(filepath)
    if not any(str(path).startswith(d) for d in ALLOWED_DIRS):
        return f"Error: Access denied to {filepath}"
    
    try:
        return path.read_text()
    except Exception as e:
        return f"Error reading file: {str(e)}"


def write_file(filepath: str, content: str) -> str:
    """Write content to a file"""
    path = Path(filepath)
    if not any(str(path).startswith(d) for d in ALLOWED_DIRS):
        return f"Error: Access denied to {filepath}"
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"Successfully wrote to {filepath}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


def list_files(directory: str = "./data/uploads") -> List[str]:
    """List files in a directory"""
    try:
        path = Path(directory)
        return [str(f) for f in path.rglob("*") if f.is_file()]
    except Exception as e:
        return [f"Error listing files: {str(e)}"]
