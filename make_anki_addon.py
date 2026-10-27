#!/usr/bin/env python3
"""Package hsk_coverage/ into hsk_coverage.ankiaddon.

Per Anki's packaging rules the zip contains the *contents* of the add-on
folder (no top-level directory) and must not include __pycache__ or
meta.json; user_files/ is excluded so an install never ships or overwrites
personal data (known_words.json, downloaded dictionary, debug log).

Of the data folders, only the per-level word lists the add-on actually
reads (plus data/SOURCES.md crediting them) are shipped — not the
character lists or other derived files. LICENSE and NOTICE from the repo
root ride along at the zip root so redistributions carry them.
"""
import fnmatch
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "hsk_coverage")
OUT = os.path.join(ROOT, "hsk_coverage.ankiaddon")
EXCLUDE_DIRS = {"__pycache__", "user_files"}
EXCLUDE_FILES = {"meta.json", ".DS_Store"}


def wanted(rel, name):
    if name in EXCLUDE_FILES:
        return False
    if rel.split(os.sep)[0] == "data":
        return fnmatch.fnmatch(name, "*_words_level*.txt") \
            or name == "SOURCES.md"
    return True


with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for extra in ("LICENSE", "NOTICE"):
        z.write(os.path.join(ROOT, extra), extra)
    for root, dirs, files in os.walk(SRC):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, SRC)
            if wanted(rel, name):
                z.write(full, rel)

print("wrote %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))
