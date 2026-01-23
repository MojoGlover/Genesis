"""
File Operations Tool Module
Provides file manipulation capabilities: read, write, replace, delete, list
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional
from .tool_registry import register_tool


@register_tool(
    name="read_file",
    description="Read contents of a file",
    category="file_ops",
    examples=[
        "read_file('/workspace/script.py')",
        "read_file('/genesis/config.json')"
    ]
)
def read_file(filepath: str) -> Dict[str, Any]:
    """
    Read and return the contents of a file
    
    Args:
        filepath: Path to the file to read
    
    Returns:
        dict with 'success', 'content', and optional 'error'
    """
    try:
        filepath = Path(filepath).expanduser().resolve()
        
        if not filepath.exists():
            return {
                'success': False,
                'error': f"File not found: {filepath}"
            }
        
        if not filepath.is_file():
            return {
                'success': False,
                'error': f"Not a file: {filepath}"
            }
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            'success': True,
            'content': content,
            'filepath': str(filepath),
            'size': len(content)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="write_file",
    description="Write content to a file (creates or overwrites)",
    category="file_ops",
    examples=[
        "write_file('/workspace/new_script.py', '# Python code here')",
        "write_file('/workspace/data.json', json.dumps(data))"
    ]
)
def write_file(filepath: str, content: str, create_dirs: bool = True) -> Dict[str, Any]:
    """
    Write content to a file, creating it if it doesn't exist
    
    Args:
        filepath: Path where to write the file
        content: Content to write
        create_dirs: Create parent directories if they don't exist
    
    Returns:
        dict with 'success' and optional 'error'
    """
    try:
        filepath = Path(filepath).expanduser().resolve()
        
        # Create parent directories if needed
        if create_dirs and not filepath.parent.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return {
            'success': True,
            'filepath': str(filepath),
            'size': len(content)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="replace_in_file",
    description="Replace text in a file (find and replace)",
    category="file_ops",
    examples=[
        "replace_in_file('/workspace/script.py', 'old_function', 'new_function')",
        "replace_in_file('/genesis/config.py', 'DEBUG = False', 'DEBUG = True')"
    ]
)
def replace_in_file(filepath: str, old_text: str, new_text: str) -> Dict[str, Any]:
    """
    Find and replace text in a file
    
    Args:
        filepath: Path to the file
        old_text: Text to find
        new_text: Text to replace with
    
    Returns:
        dict with 'success', 'replacements' count, and optional 'error'
    """
    try:
        # Read current content
        result = read_file(filepath)
        if not result['success']:
            return result
        
        content = result['content']
        
        # Check if old_text exists
        if old_text not in content:
            return {
                'success': False,
                'error': f"Text not found in file: '{old_text}'"
            }
        
        # Count occurrences
        count = content.count(old_text)
        
        # Replace
        new_content = content.replace(old_text, new_text)
        
        # Write back
        write_result = write_file(filepath, new_content)
        
        if write_result['success']:
            return {
                'success': True,
                'filepath': str(filepath),
                'replacements': count
            }
        else:
            return write_result
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="delete_file",
    description="Delete a file",
    category="file_ops",
    examples=[
        "delete_file('/workspace/temp.py')",
        "delete_file('/workspace/old_script.py')"
    ]
)
def delete_file(filepath: str) -> Dict[str, Any]:
    """
    Delete a file
    
    Args:
        filepath: Path to the file to delete
    
    Returns:
        dict with 'success' and optional 'error'
    """
    try:
        filepath = Path(filepath).expanduser().resolve()
        
        if not filepath.exists():
            return {
                'success': False,
                'error': f"File not found: {filepath}"
            }
        
        if not filepath.is_file():
            return {
                'success': False,
                'error': f"Not a file: {filepath}"
            }
        
        filepath.unlink()
        
        return {
            'success': True,
            'filepath': str(filepath)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="list_directory",
    description="List files and directories in a path",
    category="file_ops",
    examples=[
        "list_directory('/workspace')",
        "list_directory('/genesis', pattern='*.py')"
    ]
)
def list_directory(dirpath: str, pattern: str = "*", recursive: bool = False) -> Dict[str, Any]:
    """
    List contents of a directory
    
    Args:
        dirpath: Path to directory
        pattern: Glob pattern to filter files (default: "*")
        recursive: Search recursively
    
    Returns:
        dict with 'success', 'files', 'directories', and optional 'error'
    """
    try:
        dirpath = Path(dirpath).expanduser().resolve()
        
        if not dirpath.exists():
            return {
                'success': False,
                'error': f"Directory not found: {dirpath}"
            }
        
        if not dirpath.is_dir():
            return {
                'success': False,
                'error': f"Not a directory: {dirpath}"
            }
        
        # Get matching paths
        if recursive:
            paths = list(dirpath.rglob(pattern))
        else:
            paths = list(dirpath.glob(pattern))
        
        files = [str(p) for p in paths if p.is_file()]
        directories = [str(p) for p in paths if p.is_dir()]
        
        return {
            'success': True,
            'path': str(dirpath),
            'files': sorted(files),
            'directories': sorted(directories),
            'total_files': len(files),
            'total_directories': len(directories)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="create_directory",
    description="Create a new directory",
    category="file_ops",
    examples=[
        "create_directory('/workspace/new_project')",
        "create_directory('/genesis/modules/new_module')"
    ]
)
def create_directory(dirpath: str, parents: bool = True) -> Dict[str, Any]:
    """
    Create a new directory
    
    Args:
        dirpath: Path for the new directory
        parents: Create parent directories if needed
    
    Returns:
        dict with 'success' and optional 'error'
    """
    try:
        dirpath = Path(dirpath).expanduser().resolve()
        
        if dirpath.exists():
            return {
                'success': False,
                'error': f"Path already exists: {dirpath}"
            }
        
        dirpath.mkdir(parents=parents, exist_ok=False)
        
        return {
            'success': True,
            'path': str(dirpath)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="copy_file",
    description="Copy a file to another location",
    category="file_ops",
    examples=[
        "copy_file('/workspace/script.py', '/workspace/backup/script.py')",
        "copy_file('/genesis/config.py', '/workspace/config.py')"
    ]
)
def copy_file(source: str, destination: str) -> Dict[str, Any]:
    """
    Copy a file to another location
    
    Args:
        source: Source file path
        destination: Destination file path
    
    Returns:
        dict with 'success' and optional 'error'
    """
    try:
        source = Path(source).expanduser().resolve()
        destination = Path(destination).expanduser().resolve()
        
        if not source.exists():
            return {
                'success': False,
                'error': f"Source file not found: {source}"
            }
        
        if not source.is_file():
            return {
                'success': False,
                'error': f"Source is not a file: {source}"
            }
        
        # Create destination directory if needed
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(source, destination)
        
        return {
            'success': True,
            'source': str(source),
            'destination': str(destination)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@register_tool(
    name="file_exists",
    description="Check if a file or directory exists",
    category="file_ops",
    examples=[
        "file_exists('/workspace/script.py')",
        "file_exists('/genesis/config.json')"
    ]
)
def file_exists(filepath: str) -> Dict[str, Any]:
    """
    Check if a file or directory exists
    
    Args:
        filepath: Path to check
    
    Returns:
        dict with 'exists', 'is_file', 'is_directory'
    """
    try:
        filepath = Path(filepath).expanduser().resolve()
        
        exists = filepath.exists()
        is_file = filepath.is_file() if exists else False
        is_directory = filepath.is_dir() if exists else False
        
        return {
            'success': True,
            'path': str(filepath),
            'exists': exists,
            'is_file': is_file,
            'is_directory': is_directory
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
