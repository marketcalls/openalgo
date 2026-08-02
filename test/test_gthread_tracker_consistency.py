"""The progress page must agree with the tracker.

The counts in docs/progress/gthread/README.md have now drifted from the CSV
three times: once when rows were resolved, once when the audit reopened 14 rows,
and once when a prose paragraph kept stale numbers after the table was updated.

Hand-maintained numbers in two places always diverge. Since these particular
numbers are what gets reported as "coverage", a stale one is not cosmetic -- it
is the overstatement this whole correction was about. So they are checked.
"""

import csv
import re
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TRACKER = REPO / "docs" / "plans" / "2026-08-01-gthread-migration-tracker.csv"
README = REPO / "docs" / "progress" / "gthread" / "README.md"


@pytest.fixture(scope="module")
def counts():
    rows = list(csv.reader(TRACKER.open(encoding="utf-8")))
    header, body = rows[0], rows[1:]
    status = header.index("status")
    return Counter(r[status] for r in body), len(body)


@pytest.fixture(scope="module")
def readme():
    return README.read_text(encoding="utf-8")


def _table_value(text, label):
    """Pull `| label | 42 |` out of the Numbers table."""
    m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*(\d+)\s*\|", text)
    assert m, f"the Numbers table has no row labelled {label!r}"
    return int(m.group(1))


def test_total_matches(counts, readme):
    _, total = counts
    assert _table_value(readme, "Total items tracked") == total


@pytest.mark.parametrize("label,status", [
    ("Already fine, no work needed", "resolved"),
    ("Fixed and tested", "done"),
    ("Still to do", "open"),
])
def test_each_status_count_matches(counts, readme, label, status):
    tally, _ = counts
    assert _table_value(readme, label) == tally[status], (
        f"README says {_table_value(readme, label)} for {label!r}, tracker has "
        f"{tally[status]} rows with status={status!r}"
    )


def test_coverage_percentage_is_arithmetically_true(counts, readme):
    """Actionable rows exclude those needing no work. This is the number that
    was overstated as 77.5%, so it is checked rather than trusted."""
    tally, total = counts
    actionable = total - tally["resolved"]
    m = re.search(r"\*\*(\d+)\s*/\s*(\d+)\s*=\s*(\d+)%\*\*", readme)
    assert m, "the Numbers table has no coverage row in the form **66 / 102 = 65%**"

    done, denom, pct = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert done == tally["done"], f"coverage numerator {done} != {tally['done']} done rows"
    assert denom == actionable, f"coverage denominator {denom} != {actionable} actionable rows"
    assert pct == round(100 * done / denom), (
        f"stated {pct}%, actual {round(100 * done / denom)}%"
    )


def test_prose_open_count_matches_the_table(readme):
    """The specific drift that was missed: the table was corrected to 36 while
    a paragraph below it still said 23."""
    table_open = _table_value(readme, "Still to do")
    m = re.search(r"Of the (\d+) items still\s*\n?to do", readme)
    assert m, "the prose no longer states an open-item count"
    assert int(m.group(1)) == table_open, (
        f"prose says {m.group(1)} open items, table says {table_open}"
    )


def test_prose_breakdown_sums_to_the_open_count(readme):
    """The bulleted split must add up, or one category has silently absorbed
    another's rows."""
    table_open = _table_value(readme, "Still to do")
    bullets = [int(n) for n in re.findall(r"- \*\*(\d+) (?:are|cannot)", readme)]
    assert bullets, "the open-item breakdown bullets are gone"
    assert sum(bullets) == table_open, (
        f"breakdown {bullets} sums to {sum(bullets)}, table says {table_open}"
    )
