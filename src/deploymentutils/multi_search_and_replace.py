
#!/usr/bin/env python3
"""
This script is intended to be uploaded to a remote server.
"""
import sys
import os
import json

assert len(sys.argv) == 2

rplmt_data_fpath = sys.argv[1]

# Read file content
with open(rplmt_data_fpath, 'r', encoding='utf-8') as fp:
    rplmt_data = json.load(fp)

target_file_path = os.path.expanduser(rplmt_data["target_file"])
with open(target_file_path, 'r', encoding='utf-8') as fp: content = fp.read()

def apply_replacement_tuple(tup, content):
    old_string = tup[0]
    new_string = tup[1]
    assert isinstance(old_string, str) and isinstance(new_string, str)
    assert len(old_string) > 0

    # Ensure old_string occurs exactly once
    occurrences = content.count(old_string)
    if occurrences == 0:
        sys.exit(f"[ERROR] '{old_string}' not found in {{file_path}}.", 1)
    elif occurrences > 1:
        sys.exit(f"[ERROR] '{old_string}' found {occurrences} times in {target_file_path}, expected 1.", 2)

    # Replace string
    new_content = content.replace(old_string, new_string, 1)
    return new_content

for tup in rplmt_data["replacements"]:
    content = apply_replacement_tuple(tup, content)

# Write updated file
with open(target_file_path, 'w', encoding='utf-8') as fp:
    fp.write(content)

print(f"successfully made {len(rplmt_data['replacements'])} edits to file {target_file_path}")
