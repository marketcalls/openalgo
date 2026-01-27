#!/usr/bin/env python3
"""
Master Contract Instrument Type Validation Test

Validates that the master contract database has standardized instrument types:
- All futures should have instrumenttype = 'FUT'
- All options should have instrumenttype = 'CE' or 'PE'

This applies across all segments: NFO, BFO, MCX, CDS
"""

import os
import sys
from collections import defaultdict

from colorama import Fore, Style
from colorama import init as colorama_init

colorama_init(autoreset=True)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set DATABASE_URL if not already set
if not os.getenv("DATABASE_URL"):
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "openalgo.db"
    )
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

from database.symbol import SymToken, db_session


def green(t):
    return f"{Fore.GREEN}{t}{Style.RESET_ALL}"


def red(t):
    return f"{Fore.RED}{t}{Style.RESET_ALL}"


def yellow(t):
    return f"{Fore.YELLOW}{t}{Style.RESET_ALL}"


def cyan(t):
    return f"{Fore.CYAN}{t}{Style.RESET_ALL}"


# Expected futures instrument types that should be converted to 'FUT'
LEGACY_FUTURES_TYPES = {"FUTIDX", "FUTSTK", "FUTCOM", "FUTCUR", "FUTIRC", "FUTIRT"}

# Expected options instrument types that should be converted to 'CE' or 'PE'
LEGACY_OPTIONS_TYPES = {"OPTIDX", "OPTSTK", "OPTFUT", "OPTCUR", "OPTIRC"}

# Exchanges to check
DERIVATIVE_EXCHANGES = ["NFO", "BFO", "MCX", "CDS"]


def test_futures_instrument_types():
    """Test that all futures have instrumenttype = 'FUT'"""
    print(cyan("\n" + "=" * 60))
    print(cyan("FUTURES INSTRUMENT TYPE VALIDATION"))
    print(cyan("=" * 60))

    violations = defaultdict(list)
    correct_count = defaultdict(int)

    for exchange in DERIVATIVE_EXCHANGES:
        # Query all records that look like futures (symbol ends with FUT or has legacy future types)
        futures = SymToken.query.filter(
            SymToken.exchange == exchange, SymToken.symbol.like("%FUT")
        ).all()

        for fut in futures:
            if fut.instrumenttype == "FUT":
                correct_count[exchange] += 1
            else:
                violations[exchange].append(
                    {"symbol": fut.symbol, "instrumenttype": fut.instrumenttype, "name": fut.name}
                )

    # Also check for any legacy futures types that weren't converted
    for legacy_type in LEGACY_FUTURES_TYPES:
        legacy_records = (
            SymToken.query.filter(SymToken.instrumenttype == legacy_type).limit(10).all()
        )

        for rec in legacy_records:
            violations[rec.exchange].append(
                {
                    "symbol": rec.symbol,
                    "instrumenttype": rec.instrumenttype,
                    "name": rec.name,
                    "note": f"Legacy type {legacy_type} not converted",
                }
            )

    # Print results
    total_correct = sum(correct_count.values())
    total_violations = sum(len(v) for v in violations.values())

    print(f"\n{cyan('Exchange-wise Results:')}")
    for exchange in DERIVATIVE_EXCHANGES:
        correct = correct_count.get(exchange, 0)
        violation_count = len(violations.get(exchange, []))

        if violation_count == 0:
            print(f"  {exchange}: {green(f'{correct} futures with FUT type')} {green('PASS')}")
        else:
            print(
                f"  {exchange}: {correct} correct, {red(f'{violation_count} violations')} {red('FAIL')}"
            )
            # Show first 5 violations
            for v in violations[exchange][:5]:
                print(f"    - {v['symbol']}: instrumenttype={red(v['instrumenttype'])}")
            if len(violations[exchange]) > 5:
                print(f"    ... and {len(violations[exchange]) - 5} more")

    print(f"\n{cyan('Summary:')}")
    print(f"  Total correct: {green(total_correct)}")
    print(f"  Total violations: {red(total_violations) if total_violations > 0 else green(0)}")

    return total_violations == 0


def test_options_instrument_types():
    """Test that all options have instrumenttype = 'CE' or 'PE'"""
    print(cyan("\n" + "=" * 60))
    print(cyan("OPTIONS INSTRUMENT TYPE VALIDATION"))
    print(cyan("=" * 60))

    violations = defaultdict(list)
    correct_count = defaultdict(int)

    for exchange in DERIVATIVE_EXCHANGES:
        # Query all records that look like options (symbol ends with CE or PE)
        ce_options = SymToken.query.filter(
            SymToken.exchange == exchange, SymToken.symbol.like("%CE")
        ).all()

        pe_options = SymToken.query.filter(
            SymToken.exchange == exchange, SymToken.symbol.like("%PE")
        ).all()

        for opt in ce_options:
            if opt.instrumenttype == "CE":
                correct_count[exchange] += 1
            else:
                violations[exchange].append(
                    {"symbol": opt.symbol, "instrumenttype": opt.instrumenttype, "expected": "CE"}
                )

        for opt in pe_options:
            if opt.instrumenttype == "PE":
                correct_count[exchange] += 1
            else:
                violations[exchange].append(
                    {"symbol": opt.symbol, "instrumenttype": opt.instrumenttype, "expected": "PE"}
                )

    # Also check for any legacy options types that weren't converted
    for legacy_type in LEGACY_OPTIONS_TYPES:
        legacy_records = (
            SymToken.query.filter(SymToken.instrumenttype == legacy_type).limit(10).all()
        )

        for rec in legacy_records:
            violations[rec.exchange].append(
                {
                    "symbol": rec.symbol,
                    "instrumenttype": rec.instrumenttype,
                    "note": f"Legacy type {legacy_type} not converted",
                }
            )

    # Print results
    total_correct = sum(correct_count.values())
    total_violations = sum(len(v) for v in violations.values())

    print(f"\n{cyan('Exchange-wise Results:')}")
    for exchange in DERIVATIVE_EXCHANGES:
        correct = correct_count.get(exchange, 0)
        violation_count = len(violations.get(exchange, []))

        if violation_count == 0:
            print(f"  {exchange}: {green(f'{correct} options with CE/PE type')} {green('PASS')}")
        else:
            print(
                f"  {exchange}: {correct} correct, {red(f'{violation_count} violations')} {red('FAIL')}"
            )
            # Show first 5 violations
            for v in violations[exchange][:5]:
                expected = v.get("expected", "CE/PE")
                print(
                    f"    - {v['symbol']}: instrumenttype={red(v['instrumenttype'])} (expected {expected})"
                )
            if len(violations[exchange]) > 5:
                print(f"    ... and {len(violations[exchange]) - 5} more")

    print(f"\n{cyan('Summary:')}")
    print(f"  Total correct: {green(total_correct)}")
    print(f"  Total violations: {red(total_violations) if total_violations > 0 else green(0)}")

    return total_violations == 0


def test_instrument_type_distribution():
    """Show distribution of instrument types across exchanges"""
    print(cyan("\n" + "=" * 60))
    print(cyan("INSTRUMENT TYPE DISTRIBUTION"))
    print(cyan("=" * 60))

    for exchange in DERIVATIVE_EXCHANGES:
        print(f"\n{yellow(exchange)}:")

        # Get distinct instrument types for this exchange
        from sqlalchemy import func

        type_counts = (
            db_session.query(SymToken.instrumenttype, func.count(SymToken.id))
            .filter(SymToken.exchange == exchange)
            .group_by(SymToken.instrumenttype)
            .all()
        )

        for itype, count in sorted(type_counts, key=lambda x: -x[1]):
            if itype in ["FUT", "CE", "PE", "EQ", "INDEX", None, ""]:
                color = green
            elif itype in LEGACY_FUTURES_TYPES or itype in LEGACY_OPTIONS_TYPES:
                color = red
            else:
                color = yellow

            itype_display = itype if itype else "(empty)"
            print(f"  {color(itype_display)}: {count}")


def main():
    print(cyan("\n" + "=" * 60))
    print(cyan("MASTER CONTRACT INSTRUMENT TYPE TEST"))
    print(cyan("=" * 60))

    # Check database connection
    try:
        total = SymToken.query.count()
        print(f"\nDatabase connected. Total records: {cyan(total)}")
    except Exception as e:
        print(red(f"\nFailed to connect to database: {e}"))
        print(
            yellow("Make sure OpenAlgo is properly configured and master contracts are downloaded.")
        )
        return 1

    # Show distribution first
    test_instrument_type_distribution()

    # Run validation tests
    futures_pass = test_futures_instrument_types()
    options_pass = test_options_instrument_types()

    # Final summary
    print(cyan("\n" + "=" * 60))
    print(cyan("FINAL RESULT"))
    print(cyan("=" * 60))

    if futures_pass and options_pass:
        print(green("\nALL TESTS PASSED"))
        print(green("Instrument types are properly standardized!"))
        return 0
    else:
        print(red("\nSOME TESTS FAILED"))
        if not futures_pass:
            print(red("- Futures instrument type validation failed"))
        if not options_pass:
            print(red("- Options instrument type validation failed"))
        print(
            yellow(
                "\nTo fix: Re-download master contracts after updating the broker's master_contract_db.py"
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
