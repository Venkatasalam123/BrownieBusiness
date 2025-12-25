#!/usr/bin/env python3
"""
Helper script to convert credentials.json to .env format
This script reads your credentials.json file and adds it to your .env file
"""

import json
import os
from pathlib import Path

def convert_credentials_to_env():
    """Convert credentials.json to .env format"""
    
    # Check if credentials.json exists
    creds_file = Path('credentials.json')
    if not creds_file.exists():
        print("❌ Error: credentials.json file not found in current directory")
        print("   Please make sure credentials.json is in the same directory as this script")
        return
    
    # Read credentials.json
    try:
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in credentials.json: {e}")
        return
    except Exception as e:
        print(f"❌ Error reading credentials.json: {e}")
        return
    
    # Ask user for format preference
    print("\nChoose format:")
    print("1. Multi-line (readable, recommended)")
    print("2. Single-line (compact)")
    choice = input("Enter choice (1 or 2, default=1): ").strip() or "1"
    
    # Read existing .env file if it exists
    env_file = Path('.env')
    env_lines = []
    if env_file.exists():
        with open(env_file, 'r') as f:
            env_lines = f.readlines()
    
    # Check if GOOGLE_CREDENTIALS_JSON already exists
    updated = False
    new_lines = []
    in_multiline_var = False
    skip_until_end = False
    
    for i, line in enumerate(env_lines):
        # Check if we're starting a GOOGLE_CREDENTIALS_JSON variable
        if line.strip().startswith('GOOGLE_CREDENTIALS_JSON='):
            if choice == "1":
                # Multi-line format - python-dotenv supports multi-line in quotes
                new_lines.append("GOOGLE_CREDENTIALS_JSON='")
                # Add formatted JSON (pretty-printed, each line on its own)
                formatted_json = json.dumps(creds_data, indent=2)
                for json_line in formatted_json.split('\n'):
                    new_lines.append(f"{json_line}\n")
                new_lines.append("'\n")
            else:
                # Single-line format
                creds_string = json.dumps(creds_data)
                new_lines.append(f"GOOGLE_CREDENTIALS_JSON='{creds_string}'\n")
            updated = True
            # Skip remaining lines of the old multi-line value if it exists
            # Check if the line doesn't end with a closing quote (multi-line)
            if not (line.rstrip().endswith("'") and line.count("'") >= 2):
                skip_until_end = True
            continue
        
        # Skip lines until we find the closing quote for multi-line values
        if skip_until_end:
            # Check if this line ends the multi-line value
            stripped = line.strip()
            if stripped.endswith("'") or stripped == "'":
                skip_until_end = False
            continue
        
        new_lines.append(line)
    
    # Add new line if it doesn't exist
    if not updated:
        new_lines.append(f"\n# Google Service Account Credentials\n")
        if choice == "1":
            # Multi-line format - python-dotenv supports multi-line in quotes
            new_lines.append("GOOGLE_CREDENTIALS_JSON='")
            formatted_json = json.dumps(creds_data, indent=2)
            for json_line in formatted_json.split('\n'):
                new_lines.append(f"{json_line}\n")
            new_lines.append("'\n")
        else:
            # Single-line format
            creds_string = json.dumps(creds_data)
            new_lines.append(f"GOOGLE_CREDENTIALS_JSON='{creds_string}'\n")
    
    # Write to .env file
    try:
        with open(env_file, 'w') as f:
            f.writelines(new_lines)
        print("✅ Successfully added GOOGLE_CREDENTIALS_JSON to .env file")
        print(f"   File: {env_file.absolute()}")
        print("\n⚠️  Important: Make sure your .env file is in .gitignore (it should be)")
        print("   Never commit your .env file to version control!")
    except Exception as e:
        print(f"❌ Error writing to .env file: {e}")
        return
    
    # Also print the value for manual copy-paste if needed
    print("\n" + "="*70)
    print("Alternative: You can manually add this to your .env file:")
    print("="*70)
    if choice == "1":
        print("GOOGLE_CREDENTIALS_JSON='")
        formatted_json = json.dumps(creds_data, indent=2)
        for json_line in formatted_json.split('\n'):
            print(json_line)
        print("'")
    else:
        creds_string = json.dumps(creds_data)
        print(f"GOOGLE_CREDENTIALS_JSON='{creds_string}'")
    print("="*70)

if __name__ == '__main__':
    print("Converting credentials.json to .env format...")
    print("-" * 70)
    convert_credentials_to_env()

