"""Step definitions for restricted-network isolation security tests."""

import os
from contextlib import suppress

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.openstack import OpenStackClient
from defining_acceptance.reporting import report
from defining_acceptance.utils import DeferStack
from tests.bdd._vm_helpers import vm_ssh

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
    running_vm: dict, demo_os_runner: OpenStackClient, ssh_runner, defer: DeferStack
):
    """Apply a security group that blocks all ICMP egress to the Background VM.

    The VM retains SSH access (TCP port 22, stateful — return traffic is
    forwarded by connection tracking), but outbound ICMP is dropped.
    """
    if MOCK_MODE:
        return

    sg_name = f"no-egress-{running_vm['server_name']}"
    server_id = running_vm["server_id"]
    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]

    with report.step(f"Checking baseline ping to 8.8.8.8 from VM at {floating_ip}"):
        baseline_result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "ping -c 3 -W 5 8.8.8.8",
            timeout=30,
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
    if baseline_result.returncode != 0:
        pytest.skip(
            "Baseline ping to 8.8.8.8 failed before applying restrictive security group"
        )
    report.note("Baseline external ping to 8.8.8.8 succeeded before SG changes")

    previous_sg_names = []
    for security_group in demo_os_runner.server_show(server_id).security_groups or []:
        sg_name_current = (
            security_group.get("name")
            if isinstance(security_group, dict)
            else getattr(security_group, "name", None)
        )
        if sg_name_current:
            previous_sg_names.append(sg_name_current)

    for previous_sg_name in previous_sg_names:
        demo_os_runner.server_remove_security_group(server_id, previous_sg_name)
        defer(demo_os_runner.server_add_security_group, server_id, previous_sg_name)

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
    port_security_groups = demo_os_runner.server_port_security_group_ids(server_id)
    assert port_security_groups, f"No Neutron ports found for server {server_id!r}"
    for port_id, security_group_ids in port_security_groups.items():
        assert sg_id in security_group_ids, (
            f"Security group {sg_id!r} is not applied on Neutron port {port_id!r}."
        )
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
            "ping -c 3 -W 5 8.8.8.8 2>&1",
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
