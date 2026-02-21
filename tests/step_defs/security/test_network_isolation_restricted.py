"""Step definitions for restricted-network isolation security tests."""

import os
from contextlib import suppress

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.openstack import OpenStackClient
from defining_acceptance.reporting import report
from defining_acceptance.utils import DeferStack
from tests._vm_helpers import vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario(
    "security/network_isolation.feature", "Restricted network cannot reach external IPs"
)
def test_restricted_network_isolation():
    pass


# ── Steps ─────────────────────────────────────────────────────────────────────


@given("the VM is on the restricted network")
def setup_vm_restricted_network(
    running_vm: dict, demo_os_runner: OpenStackClient, defer: DeferStack
):
    """Apply a security group that blocks all ICMP egress to the Background VM.

    The VM retains SSH access (TCP port 22, stateful — return traffic is
    forwarded by connection tracking), but outbound ICMP is dropped.
    """
    if MOCK_MODE:
        return

    sg_name = f"no-egress-{running_vm['server_name']}"
    server_id = running_vm["server_id"]

    sg = demo_os_runner.security_group_create(
        sg_name, description="Blocks egress for isolation test"
    )
    sg_id = sg["id"]
    defer(demo_os_runner.security_group_delete, sg_id)

    # Remove the auto-created allow-all egress rules.
    for rule in demo_os_runner.security_group_rule_list(sg_id):
        if rule.direction == "egress":
            with suppress(Exception):
                demo_os_runner.security_group_rule_delete(rule.id)

    # Allow SSH ingress so we can still test from outside.
    demo_os_runner.security_group_rule_create(
        sg_id, direction="ingress", protocol="tcp", dst_port="22"
    )

    running_vm["isolation_sg_id"] = sg_id

    demo_os_runner.server_add_security_group(server_id, sg_name)
    defer(demo_os_runner.server_remove_security_group, server_id, sg_name)
    report.note(f"Security group {sg_name!r} applied — egress blocked")


@pytest.fixture
def isolation_result() -> dict:
    return {}


@pytest.fixture
@when("I attempt to ping an external IP")
def ping_external_ip(running_vm, ssh_runner, isolation_result):
    """From inside the VM, try to ping 8.8.8.8 (expected to fail)."""
    if MOCK_MODE:
        isolation_result["blocked"] = True
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]

    with report.step(f"Pinging 8.8.8.8 from VM at {floating_ip}"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "ping -c 3 -W 5 8.8.8.8 2>&1; echo exit:$?",
            timeout=30,
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
    isolation_result["returncode"] = result.returncode
    isolation_result["stdout"] = result.stdout


@then("the connection should be blocked")
def verify_connection_blocked(isolation_result):
    """Assert the outbound ping failed (egress blocked by security group)."""
    if MOCK_MODE:
        return
    assert isolation_result.get("returncode", 0) != 0, (
        "Expected ping to 8.8.8.8 to be blocked, but it succeeded.\n"
        f"stdout: {isolation_result.get('stdout')}"
    )
    report.note("External ping correctly blocked by security group egress rules")
