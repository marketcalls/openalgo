import os
import sys
import re
from pathlib import Path

# run command = python3 /Users/deepaknesarikar/Desktop/upload_all.py

# Auto-switch to virtual environment python if duckdb is not installed in current python
VENV_PYTHON = "/Users/deepaknesarikar/openalgo-charts-terminal/venv/bin/python"
try:
    import duckdb
    import pandas
except ImportError:
    if os.path.exists(VENV_PYTHON) and sys.executable != VENV_PYTHON:
        print(f"Switching to OpenAlgo virtual environment python: {VENV_PYTHON} ...")
        os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

PROJECT_DIR = "/Users/deepaknesarikar/openalgo-charts-terminal"
DB_PATH = os.path.join(PROJECT_DIR, "db", "historify.duckdb")
os.environ["HISTORIFY_DATABASE_PATH"] = DB_PATH

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from database.historify_db import import_from_csv

EXCHANGE = "NFO"
INTERVAL = "1m"

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", 
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

def extract_symbol(filename: str) -> str:
    """
    Transforms: NIFTY50_2025-12-09_26150_PE_2025-12-01_to_2025-12-09_1m.csv
    Into:       NIFTY09DEC2526150PE
    """
    base = Path(filename).name
    pattern1 = r"^([A-Za-z0-9]+)_(\d{4})-(\d{2})-(\d{2})_(\d+(?:\.\d+)?)_([CP]E)"
    match = re.match(pattern1, base, re.IGNORECASE)
    if match:
        underlying_raw, year, month, day, strike, opt_type = match.groups()
        underlying = "NIFTY" if underlying_raw.upper() in ["NIFTY50", "NIFTY"] else underlying_raw.upper()
        month_idx = int(month) - 1
        if 0 <= month_idx < 12:
            month_str = MONTHS[month_idx]
            year_short = year[-2:]
            return f"{underlying}{day}{month_str}{year_short}{strike}{opt_type.upper()}"

    pattern2 = r"^([A-Za-z0-9]+)(\d{2}[A-Za-z]{3}\d{2})(\d+)([CP]E)"
    match2 = re.match(pattern2, base, re.IGNORECASE)
    if match2:
        return match2.group(0).upper()

    return None

def find_target_files():
    candidates = []
    
    if len(sys.argv) > 1:
        custom_path = Path(sys.argv[1]).expanduser()
        if custom_path.is_dir():
            candidates.append(custom_path)
        elif custom_path.is_file():
            sym = extract_symbol(custom_path.name)
            if sym:
                return [(custom_path, sym)]

    downloads_dir = Path.home() / "Downloads"
    workspace_dir = Path(__file__).resolve().parent / "uploads_csv"
    desktop_sub = Path.home() / "Desktop" / "nifty_csv"
    desktop_dir = Path.home() / "Desktop"

    for d in [downloads_dir, workspace_dir, desktop_sub, desktop_dir]:
        if d.exists():
            candidates.append(d)

    seen = set()
    target_files = []

    for folder in candidates:
        try:
            for file in sorted(folder.glob("*.csv")):
                if file.name in seen:
                    continue
                sym = extract_symbol(file.name)
                if sym:
                    seen.add(file.name)
                    target_files.append((file, sym))
            if target_files:
                print(f"Loaded {len(target_files)} target file(s) from {folder}")
                break
        except (PermissionError, OSError) as e:
            continue

    return target_files

def main():
    target_files = find_target_files()

    if not target_files:
        print("\n[!] No matching CSV files found.")
        print("Please check your Downloads folder or specify a directory path.")
        return

    print(f"\n========================================================")
    print(f"Importing {len(target_files)} file(s) into Historify DuckDB")
    print(f"Exchange: {EXCHANGE} | Interval: {INTERVAL}")
    print(f"Database: {DB_PATH}")
    print(f"========================================================\n")

    success_count = 0
    fail_count = 0
    total_records = 0

    for idx, (filepath, symbol) in enumerate(target_files, start=1):
        print(f"[{idx}/{len(target_files)}] Importing {filepath.name}")
        print(f"    --> Symbol: {symbol}")
        
        try:
            success, msg, records = import_from_csv(
                file_path=str(filepath),
                symbol=symbol,
                exchange=EXCHANGE,
                interval=INTERVAL
            )
            if success:
                print(f"    ✓ SUCCESS: {msg} ({records} records)")
                success_count += 1
                total_records += records
            else:
                print(f"    ✗ FAILED: {msg}")
                fail_count += 1
        except Exception as e:
            print(f"    ✗ ERROR: {e}")
            fail_count += 1

    print(f"\n========================================================")
    print(f"Finished! Successfully imported: {success_count}/{len(target_files)} files")
    print(f"Total candles imported: {total_records}")
    if fail_count > 0:
        print(f"Failed imports: {fail_count}")
    print(f"========================================================\n")

if __name__ == "__main__":
    main()
