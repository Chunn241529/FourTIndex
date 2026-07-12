import re
import sys
import os

def bump_version(filepath):
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        sys.exit(1)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Match version="X.Y.Z"
    pattern = r'version="(\d+)\.(\d+)\.(\d+)"'
    match = re.search(pattern, content)
    
    if not match:
        print("Error: Could not find version string in setup.py")
        sys.exit(1)

    major, minor, patch = map(int, match.groups())
    
    # Increment patch version
    new_patch = patch + 1
    old_version = f'{major}.{minor}.{patch}'
    new_version = f'{major}.{minor}.{new_patch}'
    
    new_content = content.replace(f'version="{old_version}"', f'version="{new_version}"')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print(f"Version bumped: {old_version} -> {new_version}")

if __name__ == "__main__":
    bump_version("setup.py")
