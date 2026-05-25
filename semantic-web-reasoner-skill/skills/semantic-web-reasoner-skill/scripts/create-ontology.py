
# /// script
# requires-python = ">=3.11"
# dependencies = ["owlready2"]   # or whatever your tool needs
# ///
"""
create-ontology.py — create OWL_DSL / owlready2 SQLite ontology and archive provenance

Positional arguments:
- ontology URI (ontology_uri): URI of ontology to create (ending with '#' or '/' if there is one)
- Ontology Base URI (ontology_base_uri): Common URI prefix for terms defined in the ontology
- OWL file (owl_file): Path to OWL file to store ontology
- working directory (working_dir): Path to working directory (/tmp/ by default)
"""
import datetime
import json
import sys
from pathlib import Path

from owlready2 import default_world, get_ontology

ontology_uri, ontology_base_uri, owl_file, working_dir = sys.argv[1:]

owl_file_name = Path(owl_file).name
sqlite_file = Path(working_dir) / f"{owl_file_name}.sqlite"

default_world.set_backend(filename=sqlite_file)
ontology = get_ontology(ontology_uri)
with open(owl_file, 'rb') as f:
    ontology.load(fileobj=f)
default_world.save()
now = datetime.datetime.now()
print(f"Saved {owl_file} to {sqlite_file} at {now.strftime('%Y-%m-%d %H:%M:%S')}")
current_time_stamp = now.strftime("%Y-%m-%d-%H-%M-%S")
archive = Path(working_dir) / 'ontology_db.json'
if not archive.exists():
    json_obj = [{
        'datetime': current_time_stamp,
        'sqlite_file': str(sqlite_file),
        'owl_file': owl_file,
        'ontology_base_uri': ontology_base_uri,
        'ontology_uri': ontology_uri,
    }]
    archive.write_text(json.dumps(json_obj, indent=4))
else:
    json_objs = json.loads(archive.read_text())
    for json_obj in json_objs:
        if json_obj['sqlite_file'] == str(sqlite_file) and json_obj['owl_file'] == owl_file:
            json_obj['datetime'] = current_time_stamp
    archive.write_text(json.dumps(json_objs, indent=4))
print(f"Archived ontology provenance to {str(archive)}")
