"""The network settings the desktop panel writes to .env (launcher.envfile).

Kept apart from test_launcher_panel.py, which needs tkinter: these run on any
Python.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from launcher import envfile

REPO = Path(__file__).resolve().parent.parent


# --- network settings ------------------------------------------------------------


def _sample() -> str:
    text = (REPO / ".sample.env").read_text(encoding="utf-8")
    return envfile.set_value(text, "REDIRECT_URL", "http://127.0.0.1:5000/zerodha/callback")


def test_apply_network_moves_every_port_and_opens_listening_only():
    out = envfile.apply_network(_sample(), envfile.Network(5050, 8800, 5600, allow_lan=True))
    v = envfile.read_values(out)
    assert (v["FLASK_HOST_IP"], v["WEBSOCKET_HOST"]) == ("0.0.0.0", "0.0.0.0")
    assert v["ZMQ_HOST"] == "127.0.0.1", "the internal bus must never be opened to the network"
    assert v["FLASK_PORT"] == "5050" and v["HOST_SERVER"] == "http://127.0.0.1:5050"
    assert v["CORS_ALLOWED_ORIGINS"] == "http://127.0.0.1:5050"
    assert v["WEBSOCKET_PORT"] == "8800" and v["WEBSOCKET_URL"] == "ws://127.0.0.1:8800"
    assert v["ZMQ_PORT"] == "5600"
    assert v["REDIRECT_URL"] == "http://127.0.0.1:5050/zerodha/callback"
    assert envfile.read_network(out) == envfile.Network(5050, 8800, 5600, True)


def test_apply_network_closes_again():
    opened = envfile.apply_network(_sample(), envfile.Network(5000, 8765, 5555, allow_lan=True))
    closed = envfile.apply_network(opened, envfile.Network(5000, 8765, 5555, allow_lan=False))
    v = envfile.read_values(closed)
    assert (v["FLASK_HOST_IP"], v["WEBSOCKET_HOST"]) == ("127.0.0.1", "127.0.0.1")


def test_apply_network_leaves_a_custom_domain_alone():
    text = envfile.set_value(_sample(), "HOST_SERVER", "https://algo.example.com")
    out = envfile.apply_network(text, envfile.Network(5050, 8765, 5555, allow_lan=False))
    v = envfile.read_values(out)
    assert v["HOST_SERVER"] == "https://algo.example.com"
    assert v["FLASK_PORT"] == "5050"


@pytest.mark.parametrize(
    ("network", "problem"),
    [
        (envfile.Network(80, 8765, 5555, False), "1024 to 65535"),
        (envfile.Network(5000, 70000, 5555, False), "1024 to 65535"),
        (envfile.Network(5000, 5000, 5555, False), "different"),
        (envfile.Network(5000, 8765, 5555, False), None),
    ],
)
def test_network_problem(network, problem):
    found = envfile.network_problem(network)
    assert (found is None) if problem is None else (problem in found)
