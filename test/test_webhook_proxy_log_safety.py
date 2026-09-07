"""Shipped deployments must never write URL webhook credentials to access logs."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROXY_TEMPLATES = (
    "install/install.sh",
    "install/install-multi.sh",
    "install/install-docker.sh",
    "install/install-docker-multi-custom-ssl.sh",
    "install/change-domain.sh",
    "install/update.sh",
)

FRESH_CONFIG_GUARDS = {
    "install/install.sh": 3,
    "install/install-multi.sh": 3,
    "install/install-docker.sh": 3,
    # The other two server blocks belong to the unrelated Portainer domain.
    "install/install-docker-multi-custom-ssl.sh": 2,
    "install/change-domain.sh": 3,
}

GUARD = re.compile(
    r"set \$openalgo_loggable 1;\s*"
    r"if \(\$uri ~ \^/\(strategy\|flow\|chartink\)/webhook/\) \{\s*"
    r"set \$openalgo_loggable 0;\s*}",
    flags=re.MULTILINE,
)


@pytest.mark.parametrize("relative_path", PROXY_TEMPLATES)
def test_every_proxy_template_suppresses_all_url_secret_routes(relative_path):
    text = (ROOT / relative_path).read_text(encoding="utf-8")

    assert "OPENALGO_WEBHOOK_LOG_GUARD" in text
    assert "strategy|flow|chartink" in text
    assert "webhook" in text
    assert "access_log" in text
    assert "if=\\$openalgo_loggable" in text or "access_log off" in text


@pytest.mark.parametrize("relative_path,expected_guards", FRESH_CONFIG_GUARDS.items())
def test_every_generated_openalgo_server_has_a_complete_conditional_log_guard(
    relative_path, expected_guards
):
    text = (ROOT / relative_path).read_text(encoding="utf-8").replace(
        "\\$", "$"
    )

    assert len(GUARD.findall(text)) == expected_guards
    access_logs = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("access_log ")
    ]
    assert access_logs
    assert all(
        "access_log off;" in line or "if=$openalgo_loggable" in line
        for line in access_logs
    )


def test_update_migration_renders_validates_and_rolls_back_the_same_guard() -> None:
    text = (ROOT / "install/update.sh").read_text(encoding="utf-8")

    for rendered_line in (
        'print indent "set $openalgo_loggable 1;"',
        'print indent "if ($uri ~ ^/(strategy|flow|chartink)/webhook/) {"',
        'print indent "    set $openalgo_loggable 0;"',
        'print indent "access_log /var/log/nginx/openalgo_access.log combined if=$openalgo_loggable;"',
    ):
        assert rendered_line in text
    assert "restore_nginx_log_guard_backups" in text
    assert "sudo nginx -t" in text


@pytest.mark.parametrize(
    "relative_path",
    ("start.sh", "install/install.sh", "install/install-multi.sh"),
)
def test_shipped_gunicorn_commands_do_not_enable_raw_access_logs(relative_path):
    text = (ROOT / relative_path).read_text(encoding="utf-8")

    assert "--access-logfile" not in text
    assert "--access-log-file" not in text
