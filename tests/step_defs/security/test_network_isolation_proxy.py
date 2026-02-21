"""Step definitions for proxy-filtering network isolation security tests."""

import os

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.reporting import report
from tests._vm_helpers import vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("security/network_isolation.feature", "Proxy filtering works")
def test_proxy_filtering():
    pass


# ── Steps ─────────────────────────────────────────────────────────────────────


@given("the VM is configured to use a proxy")
def setup_vm_with_proxy(running_vm, testbed):
    """Skip unless a proxy is declared in the testbed configuration.

    Records the proxy URL in *running_vm* for use by the @when step.
    """
    if MOCK_MODE:
        running_vm["proxy_url"] = "http://proxy.mock:3128"
        return

    if not testbed.has_proxy:
        pytest.skip(
            "No proxy configured in testbed — "
            "set network.proxy.enabled: true and provide http/https URLs"
        )

    proxy = testbed.network.proxy
    proxy_url = proxy.http or proxy.https
    assert proxy_url, "Proxy is enabled but no http/https URL is set"
    running_vm["proxy_url"] = proxy_url
    report.note(f"Using proxy: {proxy_url}")


@pytest.fixture
def proxy_result() -> dict:
    return {}


@pytest.fixture
@when("I make a web request")
def make_web_request(running_vm, ssh_runner, proxy_result):
    """From inside the VM, make an HTTP request explicitly through the proxy."""
    if MOCK_MODE:
        proxy_result["through_proxy"] = True
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    proxy_url = running_vm["proxy_url"]

    with report.step(f"HTTP request via proxy {proxy_url}"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            (
                f"curl -s --max-time 15 --proxy {proxy_url}"
                f" -o /dev/null -w '%{{http_code}}'"
                f" http://connectivity-check.ubuntu.com/"
            ),
            timeout=30,
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
    proxy_result["success"] = result.succeeded
    proxy_result["http_code"] = result.stdout.strip()
    proxy_result["proxy_url"] = proxy_url


@then("the request should go through the proxy")
def verify_proxy_used(proxy_result):
    """Assert the curl request via the proxy returned a successful HTTP code."""
    if MOCK_MODE:
        return
    assert proxy_result["success"], f"curl via proxy {proxy_result['proxy_url']} failed"
    http_code = proxy_result["http_code"]
    assert http_code.startswith("2") or http_code.startswith("3"), (
        f"Unexpected HTTP response via proxy: {http_code}"
    )
    report.note(
        f"Web request via {proxy_result['proxy_url']} returned HTTP {http_code}"
    )
