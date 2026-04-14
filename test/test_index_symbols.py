"""
Test script to verify NSE_INDEX and BSE_INDEX symbol normalization
across all broker master contracts.

Usage:
    # Test all brokers (uses the currently configured broker's database)
    uv run python test/test_index_symbols.py

    # The script queries the live symtoken table, so master contracts
    # must be downloaded first for the configured broker.
"""

import os
import sys

# Add parent directory to path so we can import from the project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Expected OpenAlgo standard symbols (from symbol_Openalgo.md)
# ---------------------------------------------------------------------------

EXPECTED_NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "NIFTYNXT50",
    "FINNIFTY",
    "BANKNIFTY",
    "MIDCPNIFTY",
    "INDIAVIX",
    "HANGSENGBEESNAV",
    "NIFTY100",
    "NIFTY200",
    "NIFTY500",
    "NIFTYALPHA50",
    "NIFTYAUTO",
    "NIFTYCOMMODITIES",
    "NIFTYCONSUMPTION",
    "NIFTYCPSE",
    "NIFTYDIVOPPS50",
    "NIFTYENERGY",
    "NIFTYFMCG",
    "NIFTYGROWSECT15",
    "NIFTYGS10YR",
    "NIFTYGS10YRCLN",
    "NIFTYGS1115YR",
    "NIFTYGS15YRPLUS",
    "NIFTYGS48YR",
    "NIFTYGS813YR",
    "NIFTYGSCOMPSITE",
    "NIFTYINFRA",
    "NIFTYIT",
    "NIFTYMEDIA",
    "NIFTYMETAL",
    "NIFTYMIDLIQ15",
    "NIFTYMIDCAP100",
    "NIFTYMIDCAP150",
    "NIFTYMIDCAP50",
    "NIFTYMIDSML400",
    "NIFTYMNC",
    "NIFTYPHARMA",
    "NIFTYPSE",
    "NIFTYPSUBANK",
    "NIFTYPVTBANK",
    "NIFTYREALTY",
    "NIFTYSERVSECTOR",
    "NIFTYSMLCAP100",
    "NIFTYSMLCAP250",
    "NIFTYSMLCAP50",
    "NIFTY100EQLWGT",
    "NIFTY100LIQ15",
    "NIFTY100LOWVOL30",
    "NIFTY100QUALTY30",
    "NIFTY200QUALTY30",
    "NIFTY50DIVPOINT",
    "NIFTY50EQLWGT",
    "NIFTY50PR1XINV",
    "NIFTY50PR2XLEV",
    "NIFTY50TR1XINV",
    "NIFTY50TR2XLEV",
    "NIFTY50VALUE20",
}

EXPECTED_BSE_INDEX_SYMBOLS = {
    "SENSEX",
    "BANKEX",
    "SENSEX50",
    "BSE100",
    "BSE150MIDCAPINDEX",
    "BSE200",
    "BSE250LARGEMIDCAPINDEX",
    "BSE400MIDSMALLCAPINDEX",
    "BSE500",
    "BSEAUTO",
    "BSECAPITALGOODS",
    "BSECARBONEX",
    "BSECONSUMERDURABLES",
    "BSECPSE",
    "BSEDOLLEX100",
    "BSEDOLLEX200",
    "BSEDOLLEX30",
    "BSEENERGY",
    "BSEFASTMOVINGCONSUMERGOODS",
    "BSEFINANCIALSERVICES",
    "BSEGREENEX",
    "BSEHEALTHCARE",
    "BSEINDIAINFRASTRUCTUREINDEX",
    "BSEINDUSTRIALS",
    "BSEINFORMATIONTECHNOLOGY",
    "BSEIPO",
    "BSELARGECAP",
    "BSEMETAL",
    "BSEMIDCAP",
    "BSEMIDCAPSELECTINDEX",
    "BSEOIL&GAS",
    "BSEPOWER",
    "BSEPSU",
    "BSEREALTY",
    "BSESENSEXNEXT50",
    "BSESMALLCAP",
    "BSESMALLCAPSELECTINDEX",
    "BSESMEIPO",
    "BSETECK",
    "BSETELECOM",
}

# Core symbols that every broker MUST have (minimum set)
CORE_NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "INDIAVIX",
}

CORE_BSE_INDEX_SYMBOLS = {
    "SENSEX",
    "BANKEX",
}


def get_project_root():
    """Get the project root directory (parent of test/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_env_value(line):
    """Extract value from a .env line like KEY = 'value' or KEY=value.
    Handles inline comments (# ...) and quoted values."""
    _, _, value = line.partition("=")
    value = value.strip()
    # Handle quoted values: extract content between matching quotes
    if value and value[0] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
    # Unquoted: strip inline comments
    if "#" in value:
        value = value[:value.index("#")].strip()
    return value


def read_env():
    """Read .env file and return a dict of key-value pairs."""
    env_path = os.path.join(get_project_root(), ".env")
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key = line.partition("=")[0].strip()
                    env_vars[key] = parse_env_value(line)
    return env_vars


def get_database_url(env_vars):
    """Get database URL, resolving relative SQLite paths to project root."""
    db_url = env_vars.get("DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        return None
    # Resolve relative sqlite paths (e.g. sqlite:///db/openalgo.db)
    # to be relative to project root, not CWD
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
        relative_path = db_url[len("sqlite:///"):]
        absolute_path = os.path.join(get_project_root(), relative_path)
        db_url = f"sqlite:///{absolute_path}"
    return db_url


def get_broker_name(env_vars):
    """Get configured broker name from REDIRECT_URL in .env."""
    import re
    redirect_url = env_vars.get("REDIRECT_URL") or os.getenv("REDIRECT_URL", "")
    match = re.search(r"/([^/]+)/callback$", redirect_url)
    if match:
        return match.group(1)
    # Fallback: first entry in VALID_BROKERS
    valid = env_vars.get("VALID_BROKERS") or os.getenv("VALID_BROKERS", "")
    return valid.split(",")[0].strip() if valid else None


def query_index_symbols(db_url, exchange):
    """Query all symbols for a given exchange from the symtoken table."""
    engine = create_engine(db_url, poolclass=NullPool, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        result = session.execute(
            text("SELECT symbol, brsymbol, name, token FROM symtoken WHERE exchange = :exchange"),
            {"exchange": exchange},
        )
        rows = result.fetchall()
        return [{"symbol": r[0], "brsymbol": r[1], "name": r[2], "token": r[3]} for r in rows]
    finally:
        session.close()
        engine.dispose()


def extract_raw_symbol(brsymbol):
    """Extract the raw symbol from a broker symbol string.

    Handles common broker formats:
      - "NSE:NIFTYIT-INDEX"  -> "NIFTYIT"
      - "BSE:UTILS-INDEX"    -> "UTILS"
      - "Nifty 50"           -> "Nifty 50"
      - "NIFTY BANK"         -> "NIFTY BANK"
      - "SENSEX"             -> "SENSEX"
    """
    raw = brsymbol
    # Strip exchange prefix (e.g., "NSE:", "BSE:")
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    # Strip common suffixes like "-INDEX"
    for suffix in ["-INDEX", " INDEX", "-IDX"]:
        if raw.upper().endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return raw


def basic_cleanup(raw):
    """Apply only basic normalization: uppercase + remove spaces and hyphens.

    This represents the minimal transformation that should happen to ALL
    index symbols. If a symbol differs from this after normalization,
    it means a broker-specific mapping was applied.
    """
    return raw.upper().replace(" ", "").replace("-", "")


def print_header(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_section(title):
    print(f"\n--- {title} ---")


def run_tests(db_url, broker_name):
    """Run all index symbol normalization tests."""
    print_header(f"Index Symbol Normalization Test - Broker: {broker_name.upper()}")

    total_pass = 0
    total_fail = 0
    total_warn = 0

    # -----------------------------------------------------------------------
    # Test NSE_INDEX
    # -----------------------------------------------------------------------
    print_section("NSE_INDEX Symbols")

    nse_rows = query_index_symbols(db_url, "NSE_INDEX")
    nse_symbols = {r["symbol"] for r in nse_rows}

    print(f"  Total NSE_INDEX symbols in database: {len(nse_rows)}")

    # Test 1: Core NSE symbols must exist
    print_section("Test 1: Core NSE_INDEX symbols present")
    for sym in sorted(CORE_NSE_INDEX_SYMBOLS):
        if sym in nse_symbols:
            print(f"  [PASS] {sym}")
            total_pass += 1
        else:
            print(f"  [FAIL] {sym} - MISSING")
            total_fail += 1

    # Test 2: Check all expected NSE symbols
    print_section("Test 2: All expected NSE_INDEX symbols")
    nse_found = EXPECTED_NSE_INDEX_SYMBOLS & nse_symbols
    nse_missing = EXPECTED_NSE_INDEX_SYMBOLS - nse_symbols
    print(f"  Found: {len(nse_found)}/{len(EXPECTED_NSE_INDEX_SYMBOLS)}")
    if nse_missing:
        print(f"  Missing ({len(nse_missing)}):")
        for sym in sorted(nse_missing):
            print(f"    [WARN] {sym}")
            total_warn += 1
    else:
        print("  All expected NSE_INDEX symbols present!")
        total_pass += len(EXPECTED_NSE_INDEX_SYMBOLS)

    # Test 3: Check no bad normalizations (e.g., spaces, lowercase, wrong names)
    print_section("Test 3: NSE_INDEX symbol format validation")
    bad_format = []
    for r in nse_rows:
        sym = r["symbol"]
        if " " in sym:
            bad_format.append((sym, "contains spaces"))
        if "-" in sym:
            bad_format.append((sym, "contains hyphens"))
        if sym != sym.upper():
            bad_format.append((sym, "not uppercase"))
    if bad_format:
        for sym, reason in bad_format:
            print(f"  [FAIL] '{sym}' - {reason} (brsymbol: {next((r['brsymbol'] for r in nse_rows if r['symbol'] == sym), '?')})")
            total_fail += 1
    else:
        print("  [PASS] All NSE_INDEX symbols are properly formatted (uppercase, no spaces/hyphens)")
        total_pass += 1

    # Test 4: Check for duplicates
    print_section("Test 4: NSE_INDEX duplicate check")
    nse_symbol_list = [r["symbol"] for r in nse_rows]
    duplicates = {s for s in nse_symbol_list if nse_symbol_list.count(s) > 1}
    if duplicates:
        for sym in sorted(duplicates):
            count = nse_symbol_list.count(sym)
            print(f"  [FAIL] '{sym}' appears {count} times")
            total_fail += 1
    else:
        print(f"  [PASS] No duplicate NSE_INDEX symbols")
        total_pass += 1

    # Test 5: Extra NSE_INDEX symbols - transformation detection
    print_section("Test 5: Extra NSE_INDEX symbols - transformation check")
    extra_nse = nse_symbols - EXPECTED_NSE_INDEX_SYMBOLS
    if extra_nse:
        print(f"  Found {len(extra_nse)} extra symbols (not in OpenAlgo doc)")
        print(f"  Checking if unlisted symbols were preserved (only basic cleanup applied):\n")
        nse_transformed = []
        nse_preserved = []
        for sym in sorted(extra_nse):
            brsym = next((r["brsymbol"] for r in nse_rows if r["symbol"] == sym), "?")
            raw = extract_raw_symbol(brsym)
            cleaned = basic_cleanup(raw)
            if sym == cleaned:
                nse_preserved.append((sym, brsym, raw))
            else:
                nse_transformed.append((sym, brsym, raw, cleaned))
        if nse_transformed:
            print(f"  [WARN] {len(nse_transformed)} unlisted symbols were TRANSFORMED beyond basic cleanup:")
            for sym, brsym, raw, cleaned in nse_transformed:
                print(f"    {brsym:40s} -> {sym:30s} (expected: {cleaned})")
            total_warn += len(nse_transformed)
        if nse_preserved:
            print(f"  [PASS] {len(nse_preserved)} unlisted symbols preserved correctly (basic cleanup only)")
            total_pass += 1
    else:
        print("  No extra symbols beyond the expected list")

    # -----------------------------------------------------------------------
    # Test BSE_INDEX
    # -----------------------------------------------------------------------
    print_section("BSE_INDEX Symbols")

    bse_rows = query_index_symbols(db_url, "BSE_INDEX")
    bse_symbols = {r["symbol"] for r in bse_rows}

    print(f"  Total BSE_INDEX symbols in database: {len(bse_rows)}")

    # Test 6: Core BSE symbols must exist
    print_section("Test 6: Core BSE_INDEX symbols present")
    for sym in sorted(CORE_BSE_INDEX_SYMBOLS):
        if sym in bse_symbols:
            print(f"  [PASS] {sym}")
            total_pass += 1
        else:
            print(f"  [FAIL] {sym} - MISSING")
            total_fail += 1

    # Test 7: Check all expected BSE symbols
    print_section("Test 7: All expected BSE_INDEX symbols")
    bse_found = EXPECTED_BSE_INDEX_SYMBOLS & bse_symbols
    bse_missing = EXPECTED_BSE_INDEX_SYMBOLS - bse_symbols
    print(f"  Found: {len(bse_found)}/{len(EXPECTED_BSE_INDEX_SYMBOLS)}")
    if bse_missing:
        print(f"  Missing ({len(bse_missing)}):")
        for sym in sorted(bse_missing):
            print(f"    [WARN] {sym}")
            total_warn += 1
    else:
        print("  All expected BSE_INDEX symbols present!")
        total_pass += len(EXPECTED_BSE_INDEX_SYMBOLS)

    # Test 8: BSE symbol format validation
    print_section("Test 8: BSE_INDEX symbol format validation")
    bad_format = []
    for r in bse_rows:
        sym = r["symbol"]
        if " " in sym:
            bad_format.append((sym, "contains spaces"))
        if "-" in sym:
            bad_format.append((sym, "contains hyphens"))
        if sym != sym.upper():
            bad_format.append((sym, "not uppercase"))
    if bad_format:
        for sym, reason in bad_format:
            print(f"  [FAIL] '{sym}' - {reason} (brsymbol: {next((r['brsymbol'] for r in bse_rows if r['symbol'] == sym), '?')})")
            total_fail += 1
    else:
        print("  [PASS] All BSE_INDEX symbols are properly formatted (uppercase, no spaces/hyphens)")
        total_pass += 1

    # Test 9: BSE duplicate check
    print_section("Test 9: BSE_INDEX duplicate check")
    bse_symbol_list = [r["symbol"] for r in bse_rows]
    duplicates = {s for s in bse_symbol_list if bse_symbol_list.count(s) > 1}
    if duplicates:
        for sym in sorted(duplicates):
            count = bse_symbol_list.count(sym)
            print(f"  [FAIL] '{sym}' appears {count} times")
            total_fail += 1
    else:
        print(f"  [PASS] No duplicate BSE_INDEX symbols")
        total_pass += 1

    # Test 10: Extra BSE_INDEX symbols - transformation detection
    print_section("Test 10: Extra BSE_INDEX symbols - transformation check")
    extra_bse = bse_symbols - EXPECTED_BSE_INDEX_SYMBOLS
    if extra_bse:
        print(f"  Found {len(extra_bse)} extra symbols (not in OpenAlgo doc)")
        print(f"  Checking if unlisted symbols were preserved (only basic cleanup applied):\n")
        bse_transformed = []
        bse_preserved = []
        for sym in sorted(extra_bse):
            brsym = next((r["brsymbol"] for r in bse_rows if r["symbol"] == sym), "?")
            raw = extract_raw_symbol(brsym)
            cleaned = basic_cleanup(raw)
            if sym == cleaned:
                bse_preserved.append((sym, brsym, raw))
            else:
                bse_transformed.append((sym, brsym, raw, cleaned))
        if bse_transformed:
            print(f"  [WARN] {len(bse_transformed)} unlisted symbols were TRANSFORMED beyond basic cleanup:")
            for sym, brsym, raw, cleaned in bse_transformed:
                print(f"    {brsym:40s} -> {sym:30s} (expected: {cleaned})")
            total_warn += len(bse_transformed)
        if bse_preserved:
            print(f"  [PASS] {len(bse_preserved)} unlisted symbols preserved correctly (basic cleanup only)")
            total_pass += 1
    else:
        print("  No extra symbols beyond the expected list")

    # -----------------------------------------------------------------------
    # Symbol-to-BrSymbol mapping table (full reference)
    # -----------------------------------------------------------------------
    print_section("Full NSE_INDEX Symbol Mapping (symbol -> brsymbol)")
    for r in sorted(nse_rows, key=lambda x: x["symbol"]):
        marker = "*" if r["symbol"] in EXPECTED_NSE_INDEX_SYMBOLS else " "
        print(f"  {marker} {r['symbol']:<30} <- {r['brsymbol']}")

    print_section("Full BSE_INDEX Symbol Mapping (symbol -> brsymbol)")
    for r in sorted(bse_rows, key=lambda x: x["symbol"]):
        marker = "*" if r["symbol"] in EXPECTED_BSE_INDEX_SYMBOLS else " "
        print(f"  {marker} {r['symbol']:<35} <- {r['brsymbol']}")

    # -----------------------------------------------------------------------
    # Unlisted symbols log (broker symbols not in OpenAlgo doc)
    # -----------------------------------------------------------------------
    print_header("UNLISTED SYMBOLS (not in OpenAlgo doc)")

    print_section(f"Unlisted NSE_INDEX symbols ({len(extra_nse)})")
    if extra_nse:
        print(f"  {'#':<4} {'Symbol':<30} {'Broker Symbol':<40} {'Status'}")
        print(f"  {'-'*4} {'-'*30} {'-'*40} {'-'*12}")
        for i, sym in enumerate(sorted(extra_nse), 1):
            row = next((r for r in nse_rows if r["symbol"] == sym), None)
            brsym = row["brsymbol"] if row else "?"
            raw = extract_raw_symbol(brsym)
            cleaned = basic_cleanup(raw)
            status = "preserved" if sym == cleaned else "MODIFIED"
            print(f"  {i:<4} {sym:<30} {brsym:<40} {status}")
    else:
        print("  None - broker provides only documented symbols")

    print_section(f"Unlisted BSE_INDEX symbols ({len(extra_bse)})")
    if extra_bse:
        print(f"  {'#':<4} {'Symbol':<30} {'Broker Symbol':<40} {'Status'}")
        print(f"  {'-'*4} {'-'*30} {'-'*40} {'-'*12}")
        for i, sym in enumerate(sorted(extra_bse), 1):
            row = next((r for r in bse_rows if r["symbol"] == sym), None)
            brsym = row["brsymbol"] if row else "?"
            raw = extract_raw_symbol(brsym)
            cleaned = basic_cleanup(raw)
            status = "preserved" if sym == cleaned else "MODIFIED"
            print(f"  {i:<4} {sym:<30} {brsym:<40} {status}")
    else:
        print("  None - broker provides only documented symbols")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print_header("TEST SUMMARY")
    print(f"  Broker:   {broker_name.upper()}")
    print(f"  PASS:     {total_pass}")
    print(f"  FAIL:     {total_fail}")
    print(f"  WARNINGS: {total_warn}")
    print(f"  NSE_INDEX: {len(nse_rows)} symbols ({len(nse_found)}/{len(EXPECTED_NSE_INDEX_SYMBOLS)} expected)")
    print(f"  BSE_INDEX: {len(bse_rows)} symbols ({len(bse_found)}/{len(EXPECTED_BSE_INDEX_SYMBOLS)} expected)")
    print()

    if total_fail > 0:
        print(f"  RESULT: FAILED ({total_fail} failures)")
    elif total_warn > 0:
        print(f"  RESULT: PASSED with warnings ({total_warn} missing optional symbols)")
    else:
        print(f"  RESULT: ALL PASSED")

    return total_fail == 0


if __name__ == "__main__":
    env_vars = read_env()
    db_url = get_database_url(env_vars)
    broker_name = get_broker_name(env_vars)

    if not db_url:
        print("ERROR: DATABASE_URL not found in .env or environment")
        print("Make sure your .env file has DATABASE_URL configured")
        sys.exit(1)

    if not broker_name:
        print("WARNING: Could not detect broker name from VALID_BROKERS")
        broker_name = "unknown"

    print(f"Database: {db_url}")
    print(f"Broker:   {broker_name}")

    success = run_tests(db_url, broker_name)
    sys.exit(0 if success else 1)
