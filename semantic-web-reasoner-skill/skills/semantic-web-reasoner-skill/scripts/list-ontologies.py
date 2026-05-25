
# /// script
# requires-python = ">=3.11"
# dependencies = []   # or whatever your tool needs
# ///
"""
list-ontologies.py — List all OWL ontologies saved as owlready 2 SQLite files

Positional arguments:
- working directory (working_dir): Path to working directory (/tmp/ by default)
"""
import json
import sys
from pathlib import Path

working_dir = sys.argv[1]

archive = Path(working_dir) / 'ontology_db.json'
if archive.exists():
    print(f"Ontology archival: {str(archive)}")
    json_objs = json.loads(archive.read_text())
    print(json.dumps(json_objs, indent=4))
else:
    print(f"No ontology archival found in {str(archive)}")
# for json_obj in json_objs:
#     sqlite_file = json_obj['sqlite_file']
#     owl_file = json_obj['owl_file']
#     ontology_uri = json_obj['ontology_uri']
#     ontology_base_uri = json_obj['ontology_base_uri']
#     print(f"owlready 2 SQLite ontology:\n"
#           f"'{owl_file}' -> '{sqlite_file}' - ({ontology_uri} / {ontology_base_uri})\n")
