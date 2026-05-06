#!/usr/bin/env python3
"""Strategy v2 — Phase 10 webhook-security normalization.

Collapses the four-way signing-method menu (NONE / BODY_SECRET /
HMAC_SHA256 / BOTH) onto a single TradingView-compatible scheme:
**every strategy carries a unique body-secret that must appear in
the webhook JSON.**

For each strategies_v2 row this migration:

  1. Sets webhook_signing_method = 'BODY_SECRET' if it isn't already.
  2. Materializes a webhook_secret if the row never had one (legacy
     NONE rows). The new value is encrypted at rest via the same
     Fernet wrapper that StrategyV2.webhook_secret uses on the ORM.
  3. Clears webhook_ip_allowlist (the dialog no longer exposes it;
     security comes from the body-secret + the SEBI-mandated broker-
     side static-IP whitelisting that's effective from 2026-04-01).

Idempotent — re-running on already-migrated rows is a no-op.

Run order: AFTER migrate_strategy_v2_phase9.py (which adds the segment /
exit_date / run_forever / exchange_cash columns). Before this migration
it's safe to skip when no v2 tables exist (fresh install).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def main() -> int:
    print("=" * 60)
    print("Strategy v2 — Phase 10 webhook-security normalization")
    print("=" * 60)
    try:
        import secrets

        from sqlalchemy import inspect, text

        # Import order matters: load .env first (above), THEN the v2 DB
        # module so the engine binds to the correct DATABASE_URL.
        from database.strategy_v2_db import StrategyV2, db_session, engine

        # Bail out cleanly if the table doesn't exist yet — Phase 0
        # creates it on a fresh install.
        if "strategies_v2" not in set(inspect(engine).get_table_names()):
            print("  [SKIP] strategies_v2 table not present; Phase 0 will create it")
            return 0

        rows = db_session.query(StrategyV2).all()
        if not rows:
            print("  [OK] No strategies present; nothing to normalize")
            return 0

        method_changed = 0
        secret_minted = 0
        allowlist_cleared = 0

        for s in rows:
            touched = False

            # 1. Force BODY_SECRET on every row.
            current_method = s.webhook_signing_method or "NONE"
            if current_method != "BODY_SECRET":
                s.webhook_signing_method = "BODY_SECRET"
                method_changed += 1
                touched = True

            # 2. Materialize a body-secret if absent. The descriptor
            #    encrypts at rest via utils/secret_box.
            if not s.webhook_secret:
                s.webhook_secret = secrets.token_hex(16)
                secret_minted += 1
                touched = True

            # 3. Clear any persisted IP allowlist (no longer exposed).
            if s.webhook_ip_allowlist:
                s.webhook_ip_allowlist = None
                allowlist_cleared += 1
                touched = True

            if touched:
                print(
                    f"  [OK] strategy #{s.id} {s.name!r}: "
                    f"method={current_method}->BODY_SECRET, "
                    f"secret_minted={s.webhook_secret is not None and secret_minted}, "
                    f"allowlist_cleared={s.webhook_ip_allowlist is None}"
                )

        if method_changed or secret_minted or allowlist_cleared:
            db_session.commit()
        else:
            print("  [OK] All strategies already normalized; nothing to do")

        print(
            f"  [DONE] method_changed={method_changed} "
            f"secret_minted={secret_minted} "
            f"allowlist_cleared={allowlist_cleared}"
        )
        # Reference text() in a no-op so static-checkers don't drop the
        # import — the SELECT above goes through the ORM but text() is
        # commonly used in similar migrations and worth keeping in scope.
        _ = text  # noqa: F841
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
