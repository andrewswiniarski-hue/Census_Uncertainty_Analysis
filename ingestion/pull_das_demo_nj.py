"""Download the 2010 Demonstration Data Product (DHC) for New Jersey.

What it does
------------
Downloads the New Jersey summary file from the Census Bureau's
2022-08-25 release of the 2010 Demonstration Data Product - DHC, plus
the companion documentation needed to parse it (README, technical
document, state geoheader layout, table matrix). Verifies the zip's
integrity and prints its contents.

Why this file: the demonstration products apply the 2020 Census
Disclosure Avoidance System (TopDown Algorithm) to confidential 2010
Census data. Comparing these noisy tables against the published 2010
counts is the only public way to observe privacy noise empirically
(project EDA #4). The 2022-08-25 release is the newest *tabulated*
demonstration product and the closest to the DHC production settings;
the newer 2023-04-03 suite ships only national microdata (15 GB) and
noisy measurement files. Provisional vintage choice pending mentor
confirmation -- see "Open Questions for Mentors" in the README.

What it needs
-------------
- Internet access (no API key; these are plain HTTPS downloads)
- ~240 MB of disk for the zip (kept zipped; parsing happens in EDA #4)

What it produces (all in data/raw/das_demo/, gitignored, regenerable)
----------------
- nj2010.dhc.zip                          (~239 MB, NJ summary file)
- 2022-08-25_README.pdf
- 2022-08-25_Technical_Document.pdf       (record layout)
- Geoheader_State.xlsx                    (geo header layout for state files)
- Table_Matrix.xlsx                       (which tables exist at which levels)

Run from the repo root:
    python ingestion/pull_das_demo_nj.py
"""

from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

import requests

BASE = (
    "https://www2.census.gov/programs-surveys/decennial/2020/program-management/"
    "data-product-planning/2010-demonstration-data-products/"
    "02-Demographic_and_Housing_Characteristics/2022-08-25_Summary_File"
)
TECHDOC = f"{BASE}/2022-08-25_Technical%20Document"

# Remote URL -> local filename. The %96 in the geoheader URL is a
# percent-encoded en dash in the Bureau's filename; we save under a
# plain ASCII name locally.
DOWNLOADS = {
    f"{BASE}/2022-08-25_Summary_File/New_Jersey/nj2010.dhc.zip": "nj2010.dhc.zip",
    f"{BASE}/2022-08-25_README.pdf": "2022-08-25_README.pdf",
    f"{TECHDOC}/2022-08-25_Technical%20Document.pdf": "2022-08-25_Technical_Document.pdf",
    f"{TECHDOC}/Geoheader_2010_Demonstration_Data_Product%96DHC_State.xlsx":
        "Geoheader_State.xlsx",
    f"{TECHDOC}/20220825_2010%20Demonstration%20Data%20Product%20-DHC_Table%20Matrix.xlsx":
        "Table_Matrix.xlsx",
}

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw" / "das_demo"

CHUNK = 1 << 20  # 1 MB


def download(url: str, dest: Path) -> None:
    """Stream a file to disk, resuming nothing (files are moderate)."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  already on disk ({dest.stat().st_size / 1e6:,.1f} MB) -- skipping")
        return
    with requests.get(url, stream=True, timeout=(30, 300)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=CHUNK):
                f.write(chunk)
                done += len(chunk)
                if total and done % (50 * CHUNK) < CHUNK:
                    print(f"    {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", flush=True)
        if total and done != total:
            tmp.unlink(missing_ok=True)
            sys.exit(f"  INCOMPLETE: got {done:,} of {total:,} bytes -- rerun.")
        tmp.rename(dest)
        print(f"  saved {dest.name} ({done / 1e6:,.1f} MB)")


def main() -> None:
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("2010 Demonstration Data Product - DHC (2022-08-25), New Jersey")
    print(f"Destination: {OUT_DIR.relative_to(REPO_ROOT)}\n")

    for url, name in DOWNLOADS.items():
        print(f"Downloading {name} ...")
        download(url, OUT_DIR / name)

    # Integrity + contents of the data zip (parsed properly in EDA #4).
    zip_path = OUT_DIR / "nj2010.dhc.zip"
    print("\nVerifying zip integrity ...")
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            sys.exit(f"CORRUPT member in zip: {bad} -- delete and rerun.")
        infos = zf.infolist()
        total_unc = sum(i.file_size for i in infos)
        print(f"  OK: {len(infos)} members, {total_unc / 1e9:,.2f} GB uncompressed")
        print(f"  {'member':<28} {'compressed':>12} {'uncompressed':>14}")
        for i in infos:
            print(f"  {i.filename:<28} {i.compress_size / 1e6:>10,.1f} MB "
                  f"{i.file_size / 1e6:>12,.1f} MB")

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s. "
          "Next: document in docs/data-dictionary.md; parse in EDA #4.")


if __name__ == "__main__":
    main()
