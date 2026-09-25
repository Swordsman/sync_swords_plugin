#!/usr/bin/env python3
"""Download all Anthropic docs and create hardlink trees.

Structure:
  download/             -- raw downloaded files (one flat dir with hashed names)
  lang/{lang}/{path}    -- organized by language
  concept/{path}/{lang} -- organized by concept, hardlinked from lang/
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).parent
DOWNLOAD = BASE / "download"
LANG_DIR = BASE / "lang"
CONCEPT_DIR = BASE / "concept"

# Load manifest
with open(BASE / "manifest.json") as f:
    manifest = json.load(f)

# Build flat download list: unique URLs (dedup by URL)
url_map = {}  # url -> None (dedup)
for lang, files in manifest["lang"].items():
    for path, title, url in files:
        url_map[url] = (lang, path)  # last write wins but all langs have same URLs anyway

for path, (title, url) in manifest["concept"].items():
    url_map[url] = (None, path)  # lang=None means concept-only

print(f"Unique URLs to download: {len(url_map)}")
print(f"(1557 links but only {len(url_map)} unique because 9 languages share the same 133 endpoint URLs)")

DOWNLOAD.mkdir(parents=True, exist_ok=True)
LANG_DIR.mkdir(parents=True, exist_ok=True)
CONCEPT_DIR.mkdir(parents=True, exist_ok=True)

def download(url):
    """Download a URL, save to download/ with a flat hash-based name."""
    # Use URL path as filename, replacing / with _
    path_part = url.replace("https://platform.claude.com/docs/en/", "")
    fname = path_part.replace("/", "_").replace(".md", "") + ".md"
    dest = DOWNLOAD / fname
    
    if dest.exists() and dest.stat().st_size > 0:
        return (url, fname, True, "cached")
    
    result = subprocess.run(
        ["curl", "-sSL", "--max-time", "30", "-o", str(dest), url],
        capture_output=True, text=True, timeout=35
    )
    
    if result.returncode != 0:
        # Remove empty/partial file
        dest.unlink(missing_ok=True)
        return (url, fname, False, f"curl exit {result.returncode}: {result.stderr[:100]}")
    
    size = dest.stat().st_size
    if size < 50:
        dest.unlink(missing_ok=True)
        return (url, fname, False, f"too small ({size} bytes)")
    
    return (url, fname, True, f"{size} bytes")


# Download in parallel
print("\nDownloading...")
success = 0
fail = 0
urls = list(url_map)

with ThreadPoolExecutor(max_workers=15) as pool:
    futures = {pool.submit(download, url): url for url in urls}
    for i, future in enumerate(as_completed(futures)):
        url, fname, ok, msg = future.result()
        if ok:
            success += 1
        else:
            fail += 1
        if (success + fail) % 100 == 0 or fail > 0:
            print(f"  [{success+fail}/{len(urls)}] ok={success} fail={fail}", end="\r", flush=True)

print(f"\nDone. ok={success} fail={fail}")

if fail > 0:
    print(f"\n{fail} downloads failed. Check errors above.")

# Build hardlink trees
print("\nBuilding hardlink trees...")

def path_to_fname(url_path):
    """Convert a URL path to the download/ filename."""
    return url_path.replace("/", "_").replace(".md", "") + ".md"

links_created = 0
dirs_created = set()

def ensure_dir(d):
    if d not in dirs_created:
        os.makedirs(d, exist_ok=True)
        dirs_created.add(d)

# 1. Language-specific files: hardlink into both trees
for lang, files in manifest["lang"].items():
    for path, title, url in files:
        fname = path_to_fname(url.replace("https://platform.claude.com/docs/en/", ""))
        src = DOWNLOAD / fname
        
        if not src.exists():
            continue
        
        # lang/{lang}/{path}
        lang_dest = LANG_DIR / lang / path
        ensure_dir(lang_dest.parent)
        if not lang_dest.exists():
            os.link(src, lang_dest)
            links_created += 1
        
        # concept/{path}/{lang}.md
        concept_dest = CONCEPT_DIR / path.replace(".md", "") / f"{lang}.md"
        ensure_dir(concept_dest.parent)
        if not concept_dest.exists():
            os.link(src, concept_dest)
            links_created += 1

# 2. Concept-only files: just one copy in concept/
for path, (title, url) in manifest["concept"].items():
    fname = path_to_fname(url.replace("https://platform.claude.com/docs/en/", ""))
    src = DOWNLOAD / fname
    
    if not src.exists():
        continue
    
    dest = CONCEPT_DIR / path
    ensure_dir(dest.parent)
    if not dest.exists():
        os.link(src, dest)
        links_created += 1

print(f"Hardlinks created: {links_created}")

# Stats
import shutil
total_size = sum(
    os.path.getsize(os.path.join(dirpath, f))
    for dirpath, _, filenames in os.walk(str(DOWNLOAD))
    for f in filenames
)
print(f"\nDownload size: {total_size / 1024 / 1024:.1f} MB ({len(os.listdir(DOWNLOAD))} files in download/)\n")

# Tree view
print("Tree:")
print(f"  download/          {len(os.listdir(DOWNLOAD))} files ({total_size / 1024 / 1024:.1f} MB)")
for lang in sorted(os.listdir(LANG_DIR)):
    n = sum(1 for _ in Path(LANG_DIR / lang).rglob("*.md"))
    print(f"  lang/{lang}/{' ' * (15-len(lang))}{n} files")
n_concept = sum(1 for _ in CONCEPT_DIR.rglob("*.md"))
n_dirs = sum(1 for _ in CONCEPT_DIR.rglob("*") if _.is_dir())
print(f"  concept/           {n_concept} files in ~{n_dirs} dirs")
print(f"\n  Total links: {links_created} (actual unique files: {len(os.listdir(DOWNLOAD))})")
