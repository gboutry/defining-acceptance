"""Step definitions for external network throughput performance tests."""

import os
import re

from defining_acceptance.clients.ssh import SSHRunner
import pytest
from pytest_bdd import scenario, then, when

from defining_acceptance.reporting import report
from tests._vm_helpers import vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# Minimum acceptable external download speed in Mbps.
_MIN_SPEED_MBPS = 10.0

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("performance/network_throughput.feature", "External network throughput")
def test_external_network_throughput():
    pass


# ── Steps ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def download_result() -> dict:
    return {}


@pytest.fixture
@when("I download data from an external source")
def download_from_external(running_vm: dict, ssh_runner: SSHRunner, download_result: dict):
    """Download a 10 MB test payload from Cloudflare and measure speed.

    ``curl`` reports the download speed in bytes/second via the
    ``%{speed_download}`` write-out format.  The request is capped at 30 s
    to avoid hanging the test suite if external access is slow.
    """
    if MOCK_MODE:
        download_result["speed_mbps"] = 50.0
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]

    with report.step("Downloading 10 MB test payload from external source"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            (
                "curl -s --max-time 30"
                " -o /dev/null"
                " -w '%{speed_download}'"
                " 'https://speed.cloudflare.com/__down?bytes=10000000'"
            ),
            timeout=45,
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )

    assert result.succeeded, (
        f"curl download failed (rc={result.returncode}):\n{result.stderr}"
    )

    speed_str = result.stdout.strip()
    # curl outputs speed in bytes/second; strip any surrounding whitespace/quotes.
    speed_str = re.sub(r"[^0-9.]", "", speed_str)
    assert speed_str, f"Could not parse curl speed output: {result.stdout!r}"

    speed_bytes_s = float(speed_str)
    speed_mbps = (speed_bytes_s * 8) / 1e6

    download_result["speed_mbps"] = speed_mbps
    report.note(f"External download speed: {speed_mbps:.1f} Mbps")


@then("download speed should be acceptable")
def check_download_speed(download_result: dict):
    """Assert the download speed is at least the configured minimum."""
    if MOCK_MODE:
        return
    speed_mbps = download_result["speed_mbps"]
    assert speed_mbps >= _MIN_SPEED_MBPS, (
        f"Download speed {speed_mbps:.1f} Mbps is below the "
        f"{_MIN_SPEED_MBPS} Mbps threshold"
    )
    report.note(f"External download {speed_mbps:.1f} Mbps ≥ {_MIN_SPEED_MBPS} Mbps ✓")
