"""Step definitions for network resilience reliability tests."""

import os
from contextlib import suppress

from defining_acceptance.clients.openstack import OpenStackClient
from defining_acceptance.utils import DeferStack
import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.reporting import report
from tests._vm_helpers import vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("reliability/network_resilience.feature", "Network ACLs enforced")
def test_network_acls_enforced():
    pass


@scenario("reliability/network_resilience.feature", "DNS resolution works")
def test_dns_resolution():
    pass


@scenario("reliability/network_resilience.feature", "Internal network communication")
def test_internal_network_communication():
    pass


# ── Scenario 1: Network ACLs enforced ─────────────────────────────────────────


@given("the VM has restricted network access")
def setup_vm_restricted_access(
    running_vm: dict, demo_os_runner: OpenStackClient, defer: DeferStack
):
    """Add a restricted security group that blocks ICMP egress.

    Creates a security group allowing only SSH ingress (stateful — return
    traffic is still forwarded), removes the default allow-all egress rules so
    that ICMP and other uninitiated outbound traffic is dropped.
    """
    if MOCK_MODE:
        return

    sg_name = f"restricted-{running_vm['server_name']}"
    server_id = running_vm["server_id"]

    # Remove the default security group from the VM to ensure only the restricted group is applied.
    demo_os_runner.run(f"server remove security group {server_id} default").check()
    sg = demo_os_runner.security_group_create(
        sg_name, description="Blocks ICMP egress for ACL test"
    )
    sg_id = sg["id"]
    defer(demo_os_runner.security_group_delete, sg_id)

    # Delete the auto-created allow-all egress rules so egress is blocked.
    existing_rules = demo_os_runner.security_group_rule_list(sg_id)
    for rule in existing_rules:
        if rule.get("direction") == "egress":
            with suppress(Exception):
                demo_os_runner.security_group_rule_delete(
                    rule.get("ID") or rule.get("id")
                )

    # Allow SSH ingress so we can still reach the VM.
    demo_os_runner.security_group_rule_create(
        sg_id, direction="ingress", protocol="tcp", dst_port="22"
    )

    running_vm["restricted_sg_id"] = sg_id
    running_vm["restricted_sg_name"] = sg_name

    # Add the restricted group to the VM.
    demo_os_runner.run(f"server add security group {server_id} {sg_name}").check()
    defer(
        demo_os_runner.run, f"server remove security group {server_id} {sg_name}"
    )



@pytest.fixture
def acl_result() -> dict:
    return {}


@pytest.fixture
@when("I attempt to connect to a blocked IP")
def attempt_blocked_connection(running_vm, ssh_runner, acl_result):
    """From inside the VM, try to ping an external IP (blocked by security group)."""
    if MOCK_MODE:
        acl_result["blocked"] = True
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    primary_ip = running_vm["primary_ip"]

    with report.step(f"Attempting to ping 1.1.1.1 from VM at {floating_ip}"):
        result = vm_ssh(
            ssh_runner,
            primary_ip,
            floating_ip,
            key_path,
            "ping -c 3 -W 5 1.1.1.1 2>&1; echo exit:$?",
            timeout=30,
        )
    # The ping will time out (non-zero exit) because ICMP egress is blocked.
    acl_result["returncode"] = result.returncode
    acl_result["stdout"] = result.stdout


@then("the connection should be refused or timeout")
def verify_connection_blocked(acl_result):
    """Assert the outbound connection failed (non-zero exit from ping)."""
    if MOCK_MODE:
        return
    assert acl_result.get("returncode", 0) != 0, (
        "Expected ping to fail (ICMP egress blocked), but it succeeded.\n"
        f"stdout: {acl_result.get('stdout')}"
    )
    report.note("Outbound ICMP correctly blocked by security group")


# ── Scenario 2: DNS resolution works ──────────────────────────────────────────


@pytest.fixture
def dns_result() -> dict:
    return {}


@pytest.fixture
@when("I resolve external hostnames")
def resolve_external_hostnames(running_vm, ssh_runner, dns_result):
    """From inside the VM, resolve a well-known public hostname."""
    if MOCK_MODE:
        dns_result["resolved"] = True
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    primary_ip = running_vm["primary_ip"]

    hostnames = ["google.com", "cloudflare.com"]
    results = {}
    for hostname in hostnames:
        with report.step(f"Resolving {hostname}"):
            r = vm_ssh(
                ssh_runner,
                primary_ip,
                floating_ip,
                key_path,
                f"host {hostname} 2>&1; echo exit:$?",
                timeout=30,
            )
        results[hostname] = r.returncode == 0

    dns_result["results"] = results


@then("DNS resolution should succeed")
def verify_dns_resolution(dns_result):
    """Assert at least one hostname resolved successfully."""
    if MOCK_MODE:
        return
    results = dns_result["results"]
    succeeded = [h for h, ok in results.items() if ok]
    assert succeeded, "DNS resolution failed for all hostnames: " + ", ".join(
        results.keys()
    )
    report.note(f"DNS resolved successfully for: {', '.join(succeeded)}")


# ── Scenario 3: Internal network communication ─────────────────────────────────


@pytest.fixture
def comm_result() -> dict:
    return {}


@pytest.fixture
@when("the VMs communicate with each other")
def vms_communicate(running_vm, second_vm, ssh_runner, comm_result):
    """Ping the second VM's internal IP from the first VM."""
    if MOCK_MODE:
        comm_result["success"] = True
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    primary_ip = running_vm["primary_ip"]
    target_ip = second_vm["internal_ip"]

    with report.step(f"Pinging {target_ip} from VM at {floating_ip}"):
        result = vm_ssh(
            ssh_runner,
            primary_ip,
            floating_ip,
            key_path,
            f"ping -c 4 -W 5 {target_ip}",
            timeout=30,
        )
    comm_result["success"] = result.succeeded
    comm_result["stdout"] = result.stdout


@then("the communication should succeed")
def verify_communication_succeeds(comm_result):
    """Assert the ping between VMs completed without packet loss."""
    if MOCK_MODE:
        return
    assert comm_result["success"], (
        f"Internal VM-to-VM ping failed.\nstdout: {comm_result.get('stdout')}"
    )
    report.note("Internal network communication confirmed")
