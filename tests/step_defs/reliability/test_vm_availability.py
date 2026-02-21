"""Step definitions for VM availability reliability tests."""

import os
import time

import pytest
from pytest_bdd import parsers, scenario, then, when

from defining_acceptance.reporting import report
from tests._vm_helpers import vm_ssh, wait_for_vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("reliability/vm_availability.feature", "VM starts successfully")
def test_vm_starts_successfully():
    pass


@scenario(
    "reliability/vm_availability.feature", "VM remains running for extended period"
)
def test_vm_remains_running():
    pass


@scenario("reliability/vm_availability.feature", "VM recovers from restart")
def test_vm_recovers_from_restart():
    pass


# ── When / Then steps ─────────────────────────────────────────────────────────


@pytest.fixture
def vm_status_result() -> dict:
    return {}


@pytest.fixture
def restart_result() -> dict:
    return {}


@pytest.fixture
@when("I check the status of all VMs")
def check_all_vm_status(demo_os_runner, vm_status_result):
    """List all servers and record their statuses."""
    if MOCK_MODE:
        vm_status_result["servers"] = [{"Status": "ACTIVE", "Name": "mock-vm"}]
        return
    with report.step("Listing all servers"):
        servers = demo_os_runner.server_list()
    vm_status_result["servers"] = servers
    report.note(f"Found {len(servers)} server(s)")


@then("all VMs should be in running state")
def verify_all_vms_running(vm_status_result):
    """Assert every listed server has status ACTIVE."""
    if MOCK_MODE:
        return
    servers = vm_status_result["servers"]
    assert servers, "No servers found in the cloud"
    non_active = [s for s in servers if s.get("Status") != "ACTIVE"]
    assert not non_active, "Some VMs are not ACTIVE: " + ", ".join(
        f"{s['Name']}={s['Status']}" for s in non_active
    )
    report.note(f"All {len(servers)} VM(s) are ACTIVE")


@then("all VMs should be reachable via SSH")
def verify_all_vms_ssh_reachable(running_vm, ssh_runner):
    """Verify the Background VM is reachable via SSH."""
    if MOCK_MODE:
        return
    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    with report.step(f"Verifying SSH reachability of {floating_ip}"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "echo ok",
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
        assert result.succeeded, (
            f"SSH to {floating_ip} failed (rc={result.returncode}):\n{result.stderr}"
        )
    report.note(f"VM at {floating_ip} is reachable via SSH")


@pytest.fixture
@when("I wait for 60 seconds")
def wait_60_seconds():
    """Pause execution for 60 seconds to test sustained uptime."""
    if MOCK_MODE:
        return
    with report.step("Waiting 60 seconds"):
        time.sleep(60)


@then("the VM should still be running")
def verify_vm_still_running(running_vm, demo_os_runner):
    """Assert the Background VM is still ACTIVE after the wait."""
    if MOCK_MODE:
        return
    server_id = running_vm["server_id"]
    with report.step(f"Checking status of {server_id}"):
        status = demo_os_runner.server_status(server_id)
    assert status == "ACTIVE", f"VM {server_id} is no longer ACTIVE: {status!r}"
    report.note(f"VM {server_id} is still ACTIVE after 60s")


@then("the VM should still be reachable via SSH")
def verify_vm_still_ssh_reachable(running_vm, ssh_runner):
    """Verify the Background VM is still accessible via SSH after the wait."""
    if MOCK_MODE:
        return
    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    with report.step(f"SSH check on {floating_ip} after wait"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "echo ok",
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
        assert result.succeeded, (
            f"SSH to {floating_ip} failed after wait:\n{result.stderr}"
        )
    report.note("VM still reachable via SSH")


@pytest.fixture
@when("I restart the VM")
def restart_vm(running_vm, demo_os_runner, restart_result):
    """Issue a hard reboot and record when it was requested."""
    if MOCK_MODE:
        restart_result["start"] = time.monotonic()
        return
    server_id = running_vm["server_id"]
    with report.step(f"Rebooting VM {server_id}"):
        # Hard reboot is faster for testing; --wait returns when ACTIVE again.
        demo_os_runner.server_reboot(server_id, hard=True, wait=False)
    restart_result["start"] = time.monotonic()
    restart_result["server_id"] = server_id


@then(parsers.parse("the VM should come back up within {seconds:d} seconds"))
def verify_vm_comes_back_up(restart_result, demo_os_runner, seconds):
    """Poll until the VM is ACTIVE or the deadline passes."""
    if MOCK_MODE:
        return
    server_id = restart_result["server_id"]
    elapsed_before_poll = time.monotonic() - restart_result["start"]
    remaining = seconds - elapsed_before_poll
    assert remaining > 0, f"Already exceeded {seconds}s before polling started"
    with report.step(f"Waiting for VM {server_id} to return to ACTIVE"):
        demo_os_runner.wait_for_server_status(
            server_id, status="ACTIVE", timeout=int(remaining)
        )
    elapsed = time.monotonic() - restart_result["start"]
    report.note(f"VM {server_id} came back up in {elapsed:.0f}s")


@then("the VM should be reachable via SSH after restart")
def verify_vm_ssh_after_restart(running_vm, ssh_runner):
    """Confirm SSH access is restored after the VM reboots."""
    if MOCK_MODE:
        return
    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]
    with report.step(f"SSH check on {floating_ip} post-restart"):
        wait_for_vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            timeout=120,
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
    report.note("VM reachable via SSH after restart")
