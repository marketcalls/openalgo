"""Guards against banning Docker gateway / RFC1918 addresses (issue #2015)."""

import pytest

from utils.ip_helper import is_infrastructure_ip


@pytest.mark.parametrize(
    "address",
    [
        "172.17.0.1",
        "172.16.0.1",
        "10.0.0.1",
        "192.168.1.20",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "169.254.1.1",
        "fc00::1",
    ],
)
def test_infrastructure_addresses_are_detected(address):
    assert is_infrastructure_ip(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",
        "1.1.1.1",
        "9.9.9.9",
        "2001:4860:4860::8888",
    ],
)
def test_public_addresses_are_not_infrastructure(address):
    assert is_infrastructure_ip(address) is False


@pytest.mark.parametrize("address", ["", "not-an-ip", "999.1.1.1", None])
def test_invalid_addresses_are_not_infrastructure(address):
    assert is_infrastructure_ip(address) is False
