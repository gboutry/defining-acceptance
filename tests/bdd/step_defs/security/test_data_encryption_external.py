"""Step definitions for external TLS enforcement security tests."""

import os

import pytest
from pytest_bdd import scenario, then, when

from defining_acceptance.clients import OpenStackClient, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import TestbedConfig

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("security/data_encryption.feature", "External connections use TLS")
def test_external_connections_tls():
    pass


# ── Steps ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def tls_result() -> dict:
    return {}


@pytest.fixture
@when("I connect to an external service")
def connect_to_service(
    admin_os_runner: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    tls_result: dict,
):
    """Verify that the public Keystone endpoint uses HTTPS with a valid certificate.

    Retrieves the public Identity endpoint URL from the service catalogue and
    uses ``curl`` (run on the primary node) to confirm TLS is negotiated.
    """
    if MOCK_MODE:
        tls_result["tls_ok"] = True
        tls_result["endpoint"] = "https://keystone.example:5000/v3"
        return

    primary_ip = testbed.primary_machine.ip

    with report.step("Retrieving public Keystone endpoint"):
        identity_endpoint = admin_os_runner.get_endpoint("identity", "public")
        assert identity_endpoint is not None, (
            "No public identity endpoint found in the service catalogue"
        )
        url = identity_endpoint.url.rstrip("/")

    assert url.startswith("https://"), (
        f"Public Keystone endpoint does not use HTTPS: {url!r}"
    )

    with report.step(f"Verifying TLS on {url}"):
        result = ssh_runner.run(
            primary_ip,
            f"curl -s --max-time 15 -o /dev/null -w '%{{http_code}}' {url}",
            timeout=30,
            attach_output=False,
        )
        http_code = result.stdout.strip()

    tls_result["tls_ok"] = result.succeeded and http_code not in ("", "000")
    tls_result["endpoint"] = url
    tls_result["http_code"] = http_code
    report.note(f"Keystone endpoint {url} returned HTTP {http_code}")


@then("TLS should be enforced")
def verify_tls_enforced(tls_result):
    """Assert the public endpoint uses HTTPS and responded successfully."""
    if MOCK_MODE:
        return
    endpoint = tls_result.get("endpoint", "")
    assert endpoint.startswith("https://"), (
        f"Public endpoint does not use HTTPS: {endpoint!r}"
    )
    assert tls_result["tls_ok"], (
        f"TLS connection to {endpoint} failed or returned no response "
        f"(HTTP {tls_result.get('http_code')})"
    )
    report.note(f"TLS confirmed on {endpoint}")
