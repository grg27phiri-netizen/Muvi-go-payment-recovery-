from pathlib import Path
import os
import subprocess
import sys

print("Checking MUVI GO media folders...")
for folder, ext in [("media/videos", ".mp4"), ("media/music", ".mp3")]:
    path = Path(folder)
    files = sorted(path.glob("*" + ext)) if path.is_dir() else []
    print("{}: {} files".format(folder, len(files)))
    for f in files:
        print("{} | {} bytes".format(f.name, f.stat().st_size))
        if f.stat().st_size == 0:
            print("WARNING: empty file")

print("File inventory complete. No files modified.")
