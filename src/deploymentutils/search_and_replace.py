
#!/usr/bin/env python3
"""
This script is intended to be uploaded to a remote server.
"""
import sys

assert len(sys.argv) == 4

target_file_path = sys.argv[1]
old_string_fpath = sys.argv[2]
new_string_fpath = sys.argv[3]

# Read file content
with open(old_string_fpath, 'r', encoding='utf-8') as f: old_string = f.read()
with open(new_string_fpath, 'r', encoding='utf-8') as f: new_string = f.read()
with open(target_file_path, 'r', encoding='utf-8') as f: content = f.read()

# Ensure old_string occurs exactly once
occurrences = content.count(old_string)
if occurrences == 0:
    sys.exit(f"[ERROR] '{old_string}' not found in {{file_path}}.", 1)
elif occurrences > 1:
    sys.exit(f"[ERROR] '{old_string}' found {{occurrences}} times in {{file_path}}, expected exactly 1.", 2)

# Replace string
new_content = content.replace(old_string, new_string, 1)

# Write updated file
with open(target_file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"successfully edited file {target_file_path}")
