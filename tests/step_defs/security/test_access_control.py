"""Step definitions for SSH access control security tests."""

import os

import pytest
from pytest_bdd import scenario, then, when

from defining_acceptance.clients.ssh import SSHError
from defining_acceptance.reporting import report
from tests._vm_helpers import vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("security/access_control.feature", "SSH with correct key succeeds")
def test_ssh_with_correct_key_succeeds():
    pass


@scenario("security/access_control.feature", "SSH without key fails")
def test_ssh_without_key_fails():
    pass


# ── When / Then ───────────────────────────────────────────────────────────────


@pytest.fixture
def ssh_result() -> dict:
    return {}


@pytest.fixture
@when("I connect with the correct SSH key")
def connect_with_key(running_vm, ssh_runner, ssh_result):
    """Attempt SSH using the keypair created for the VM."""
    if MOCK_MODE:
        ssh_result["success"] = True
        return

    floating_ip = running_vm["floating_ip"]
    key_path = running_vm["key_path"]

    with report.step(f"SSH to {floating_ip} with correct key"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "echo authenticated",
            proxy_jump_host=running_vm.get("proxy_jump_host"),
        )
    ssh_result["success"] = result.succeeded
    ssh_result["stdout"] = result.stdout


@then("the connection should succeed")
def check_connection_success(ssh_result):
    """Assert SSH with the correct key produced a zero exit code."""
    if MOCK_MODE:
        return
    assert ssh_result["success"], (
        f"SSH with correct key unexpectedly failed.\nstdout: {ssh_result.get('stdout')}"
    )
    report.note("SSH with correct key succeeded")


@pytest.fixture
def no_key_result() -> dict:
    return {}


@pytest.fixture
@when("I connect without an SSH key")
def connect_without_key(running_vm, ssh_runner, no_key_result):
    """Attempt SSH without any private key (password auth disabled by default)."""
    if MOCK_MODE:
        no_key_result["success"] = False
        return

    floating_ip = running_vm["floating_ip"]

    with report.step(f"SSH to {floating_ip} without key (expect failure)"):
        # Do not offer any private key; the VM should refuse auth.
        try:
            result = ssh_runner.run(
                floating_ip,
                command="echo ok",
                timeout=10,
                attach_output=False,
                proxy_jump_host=running_vm.get("proxy_jump_host"),
                use_private_key=False,
            )
            no_key_result["success"] = result.succeeded
            no_key_result["returncode"] = result.returncode
        except SSHError:
            no_key_result["success"] = False
            no_key_result["returncode"] = 255


@then("the connection should be refused")
def check_connection_refused(no_key_result):
    """Assert SSH without a key was denied (non-zero exit)."""
    if MOCK_MODE:
        return
    assert not no_key_result["success"], (
        "SSH without a key unexpectedly succeeded — "
        "the VM may allow password-less login"
    )
    report.note("SSH without key correctly refused")
