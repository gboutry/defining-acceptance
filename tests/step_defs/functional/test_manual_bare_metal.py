"""Step definitions for manual bare metal provisioning tests."""

import os

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("functional/manual-bare-metal.feature", "Prepare node for bootstrap")
def test_prepare_node():
    pass


@scenario("functional/manual-bare-metal.feature", "Bootstrap single-node cloud")
def test_bootstrap_single_node():
    pass


# ── Background ────────────────────────────────────────────────────────────────

# Minimum hardware requirements for a Sunbeam single-node deployment.
_MIN_CPUS = 4
_MIN_RAM_MB = 16_000
_MIN_DISK_GB = 100


@given("a machine meets minimum hardware requirements")
def verify_hardware_requirements(ssh_runner, testbed):
    """Check that the primary machine has sufficient CPU, RAM, and disk."""
    if MOCK_MODE:
        return
    ip = testbed.primary_machine.ip
    with report.step("Checking hardware requirements"):
        cpus = int(ssh_runner.run(ip, "nproc", attach_output=False).stdout.strip())
        ram_mb = int(
            ssh_runner.run(
                ip, "free -m | awk '/^Mem:/{print $2}'", attach_output=False
            ).stdout.strip()
        )
        disk_gb = int(
            ssh_runner.run(
                ip,
                'df -BG / | awk \'NR==2{gsub("G","",$4); print $4}\'',
                attach_output=False,
            ).stdout.strip()
        )

        assert cpus >= _MIN_CPUS, f"Insufficient CPUs: {cpus} < {_MIN_CPUS}"
        assert ram_mb >= _MIN_RAM_MB, (
            f"Insufficient RAM: {ram_mb} MB < {_MIN_RAM_MB} MB"
        )
        assert disk_gb >= _MIN_DISK_GB, (
            f"Insufficient disk: {disk_gb} GB free < {_MIN_DISK_GB} GB"
        )
        report.note(
            f"Hardware OK: {cpus} CPUs, {ram_mb} MB RAM, {disk_gb} GB disk free"
        )


@given("Ubuntu Server 24.04 LTS is installed")
def verify_ubuntu_installed(ssh_runner, testbed):
    """Check the OS is Ubuntu 24.04 LTS."""
    if MOCK_MODE:
        return
    ip = testbed.primary_machine.ip
    with report.step("Checking OS version"):
        result = ssh_runner.run(
            ip, '. /etc/os-release && echo "$PRETTY_NAME"', attach_output=False
        )
        pretty_name = result.stdout.strip()
        assert "Ubuntu 24.04" in pretty_name, (
            f"Expected Ubuntu 24.04, got: {pretty_name!r}"
        )
        report.note(f"OS: {pretty_name}")


@given("the openstack snap is installed")
def verify_snap_installed(ssh_runner, testbed):
    """Check the openstack snap is present on the primary machine."""
    if MOCK_MODE:
        return
    ip = testbed.primary_machine.ip
    channel = testbed.deployment.channel if testbed.deployment else "2024.1/edge"
    with report.step("Checking openstack snap"):
        result = ssh_runner.run(ip, "snap list openstack", attach_output=False)
        assert result.succeeded, (
            f"openstack snap is not installed — "
            f"run: sudo snap install openstack --channel {channel}"
        )


# ── Scenario 1: Prepare node ──────────────────────────────────────────────────


@pytest.fixture
def prepare_node_result() -> dict:
    return {}


@when("I run the prepare-node-script")
def run_prepare_node_script(sunbeam_client, testbed, prepare_node_result):
    """Run sunbeam prepare-node-script on the primary machine."""
    if MOCK_MODE:
        prepare_node_result["result"] = CommandResult(
            command="mock", returncode=0, stdout="mock", stderr=""
        )
        return
    result = sunbeam_client.prepare_node(testbed.primary_machine, bootstrap=True)
    prepare_node_result["result"] = result


@then("the node should be ready for bootstrap")
def verify_node_ready(ssh_runner, testbed, prepare_node_result):
    """Verify the script succeeded and left the node in the expected state."""
    if MOCK_MODE:
        return
    result: CommandResult = prepare_node_result["result"]
    assert result.succeeded, (
        f"prepare-node-script failed (rc={result.returncode})\nstderr: {result.stderr}"
    )

    ip = testbed.primary_machine.ip
    with report.step("Checking node readiness"):
        # prepare-node-script adds ubuntu to the snap_daemon group
        groups = ssh_runner.run(ip, "groups ubuntu", attach_output=False)
        assert "snap_daemon" in groups.stdout, (
            "User 'ubuntu' is not in snap_daemon group — "
            "prepare-node-script may not have completed successfully"
        )
        report.note("Node ready: ubuntu is in snap_daemon group")


# ── Scenario 2: Bootstrap ─────────────────────────────────────────────────────


@pytest.fixture
def bootstrap_result() -> dict:
    return {}


@given("the node is prepared")
def node_prepared(sunbeam_client, testbed):
    """Re-run prepare-node to ensure the node is in the right state.

    prepare-node-script is idempotent, so running it again is safe even if
    Scenario 1 already executed it.
    """
    if MOCK_MODE:
        return
    result = sunbeam_client.prepare_node(testbed.primary_machine, bootstrap=True)
    assert result.succeeded or "already" in result.stdout.lower(), (
        f"prepare-node-script failed (rc={result.returncode})\n{result.stderr}"
    )


@when("I bootstrap the cloud with default roles")
def bootstrap_cloud(sunbeam_client, testbed, bootstrap_result):
    """Bootstrap the Sunbeam cluster using the roles configured in the testbed."""
    if MOCK_MODE:
        bootstrap_result["result"] = CommandResult(
            command="mock", returncode=0, stdout="mock", stderr=""
        )
        bootstrap_result["role"] = "control,compute,storage"
        return
    machine = testbed.primary_machine
    role = ",".join(machine.roles) if machine.roles else "control,compute,storage"
    manifest = testbed.deployment.manifest if testbed.deployment else None

    result = sunbeam_client.bootstrap(
        testbed.primary_machine, role=role, manifest_path=manifest
    )
    bootstrap_result["result"] = result
    bootstrap_result["role"] = role


@then("the cloud should be bootstrapped successfully")
def verify_cloud_bootstrapped(sunbeam_client, testbed, bootstrap_result):
    """Verify the bootstrap command exited cleanly and the cluster reports ready."""
    if MOCK_MODE:
        return
    result: CommandResult = bootstrap_result["result"]
    assert result.succeeded, (
        f"Bootstrap failed (rc={result.returncode})\nstderr: {result.stderr}"
    )
    sunbeam_client.wait_for_ready(testbed.primary_machine, timeout=600)


@then("the cloud should have control, compute, and storage roles")
def verify_roles(sunbeam_client, testbed):
    """Verify the cluster status output lists all expected roles."""
    if MOCK_MODE:
        return
    status = sunbeam_client.cluster_status(testbed.primary_machine)
    for role in ("control", "compute", "storage"):
        assert role in status.stdout.lower(), (
            f"Role '{role}' not found in cluster status output:\n{status.stdout}"
        )
