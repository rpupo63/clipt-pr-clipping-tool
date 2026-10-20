#!/usr/bin/env python3
"""
Script to update all packages in requirements.txt to their latest versions.
Queries PyPI API to get the latest version for each package.
"""

import re
import json
import urllib.request
from urllib.error import URLError, HTTPError
from typing import List, Tuple

def get_latest_version(package_name: str) -> str:
    """
    Query PyPI API to get the latest version of a package.
    
    Args:
        package_name: Name of the package
        
    Returns:
        Latest version string, or None if not found
    """
    # Normalize package name (PyPI uses lowercase)
    package_name = package_name.lower().replace('_', '-')
    
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
            return data['info']['version']
    except (URLError, HTTPError) as e:
        print(f"  Warning: Could not fetch version for {package_name}: {e}")
        return None
    except KeyError:
        print(f"  Warning: Could not parse version for {package_name}")
        return None
    except Exception as e:
        print(f"  Warning: Unexpected error for {package_name}: {e}")
        return None

def parse_requirements_file(file_path: str) -> List[Tuple[str, str, str]]:
    """
    Parse requirements.txt and return list of (name, current_version, line_content).
    
    Args:
        file_path: Path to requirements.txt
        
    Returns:
        List of tuples containing package name, version, and full line
    """
    packages = []
    with open(file_path, 'r') as f:
        for line in f:
            original_line = line.rstrip()
            line = line.strip()
            if not line or line.startswith('#'):
                packages.append((None, None, original_line))
                continue
            
            # Match package name and version (format: package==version)
            # Split on == to get package name and version
            if '==' in line:
                parts = line.split('==', 1)
                package_name = parts[0].strip()
                version = parts[1].strip()
                packages.append((package_name, version, original_line))
            elif '>=' in line or '<=' in line or '>' in line or '<' in line:
                # Handle other operators - extract package name
                match = re.match(r'^([a-zA-Z0-9_.-]+)', line)
                if match:
                    package_name = match.group(1)
                    packages.append((package_name, None, original_line))
                else:
                    packages.append((None, None, original_line))
            else:
                # Just package name, no version specified
                packages.append((line, None, original_line))
    
    return packages

def update_requirements_file(file_path: str, packages: List[Tuple[str, str, str, str]]):
    """
    Write updated requirements to file.
    
    Args:
        file_path: Path to requirements.txt
        packages: List of (name, old_version, new_version, original_line)
    """
    with open(file_path, 'w') as f:
        for name, old_version, new_version, original_line in packages:
            if not name:
                # Comments or empty lines - keep as is
                f.write(f"{original_line}\n")
            elif new_version:
                # Write updated line with new version
                f.write(f"{name}=={new_version}\n")
            else:
                # No new version found, keep original line
                f.write(f"{original_line}\n")

def main():
    requirements_file = "requirements.txt"
    
    print(f"Reading {requirements_file}...")
    packages = parse_requirements_file(requirements_file)
    
    print(f"\nFound {len([p for p in packages if p[0]])} packages to update.")
    print("Checking latest versions on PyPI...\n")
    
    updated_packages = []
    updated_count = 0
    skipped_count = 0
    
    for name, current_version, line in packages:
        if not name:
            # Comments or empty lines - keep as is
            updated_packages.append((name, None, None, line))
            continue
        
        print(f"Checking {name}...", end=" ")
        latest_version = get_latest_version(name)
        
        if latest_version:
            if current_version != latest_version:
                print(f"Updating {current_version} -> {latest_version}")
                updated_packages.append((name, current_version, latest_version, line))
                updated_count += 1
            else:
                print(f"Already at latest version ({latest_version})")
                updated_packages.append((name, current_version, latest_version, line))
        else:
            print(f"Keeping current version ({current_version})")
            updated_packages.append((name, current_version, current_version, line))
            skipped_count += 1
    
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Updated: {updated_count} packages")
    print(f"  Skipped: {skipped_count} packages (errors)")
    print(f"{'='*60}")
    
    if updated_count > 0:
        update_requirements_file(requirements_file, updated_packages)
        print(f"\n✓ Successfully updated {requirements_file}")
        print(f"✓ {updated_count} packages updated to their latest versions")
    else:
        print("\nAll packages are already at their latest versions!")

if __name__ == "__main__":
    main()
