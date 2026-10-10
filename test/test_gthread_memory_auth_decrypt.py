"""Failed token decryptions must not retain one fingerprint per bad token forever."""


def test_failed_decrypt_dedupe_stays_bounded_across_unique_tokens(monkeypatch):
    from database import auth_db

    auth_db._decrypt_failure_fingerprints.clear()
    failures = []
    repeats = []
    monkeypatch.setattr(auth_db.logger, "exception", failures.append)
    monkeypatch.setattr(auth_db.logger, "debug", repeats.append)
    try:
        for index in range(400):
            assert auth_db.decrypt_token(f"bad-ciphertext-{index}") is None

        assert len(auth_db._decrypt_failure_fingerprints) <= 256
        assert len(failures) == 400

        assert auth_db.decrypt_token("bad-ciphertext-399") is None
        assert len(failures) == 400
        assert len(repeats) == 1
    finally:
        auth_db._decrypt_failure_fingerprints.clear()
