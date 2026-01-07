"""
Example: Using the AI Workspace

This shows how to use the workspace manager to execute code,
manage files, and build projects safely.
"""

from core.workspace import workspace

# Execute a simple command
print("1. Execute command:")
result = workspace.execute("echo 'Hello from workspace!'")
print(result["stdout"])

# Write a Python script
print("\n2. Write Python script:")
code = """
import math

def calculate_circle_area(radius):
    return math.pi * radius ** 2

if __name__ == "__main__":
    for r in [1, 5, 10]:
        area = calculate_circle_area(r)
        print(f"Circle with radius {r}: area = {area:.2f}")
"""

workspace.write_file("/workspace/circle.py", code)
print("Script written")

# Execute the script
print("\n3. Run the script:")
result = workspace.execute("python /workspace/circle.py")
print(result["stdout"])

# Install a package and use it
print("\n4. Install and use package:")
workspace.install_package("requests")
result = workspace.execute("python -c 'import requests; print(requests.__version__)'")
print(f"Requests version: {result['stdout']}")

# List workspace contents
print("\n5. Workspace contents:")
result = workspace.list_directory()
print(result["listing"])

print("\n✅ Workspace demo complete!")
