import json
import os
import sys

file_path = os.path.abspath(__file__)
project_root = os.path.dirname(file_path)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.download_all_tles import requestTles

all_cat = requestTles()
print(f"Loaded {len(all_cat)} TLEs.")
