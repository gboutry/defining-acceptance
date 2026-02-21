"""Step definitions for storage availability reliability tests."""

import os
import uuid

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.openstack import OpenStackClient
from defining_acceptance.clients.ssh import SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import TestbedConfig
from defining_acceptance.utils import DeferStack
from tests._vm_helpers import create_vm, vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("reliability/storage_availability.feature", "VM with volume can be spawned")
def test_vm_with_volume_spawn():
    pass


@scenario(
    "reliability/storage_availability.feature",
    "Storage remains available when one OSD host fails",
)
def test_storage_survives_osd_failure():
    pass


# ── Background ────────────────────────────────────────────────────────────────


@given("a 3-node deployment exists")
def verify_three_node_deployment(testbed):
    """Assert the testbed has at least 3 machines with storage roles."""
    if MOCK_MODE:
        return
    storage_machines = [m for m in testbed.machines if "storage" in (m.roles or [])]
    assert len(testbed.machines) >= 3, (
        f"Expected at least 3 machines, got {len(testbed.machines)}"
    )
    assert len(storage_machines) >= 3, (
        f"Expected at least 3 storage nodes, got {len(storage_machines)}"
    )
    report.note(f"3-node deployment verified: {len(storage_machines)} storage node(s)")


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _create_vm_with_volume(
    openstack_client: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    defer: DeferStack,
) -> dict:
    """Create a VM with a volume attached and a floating IP; register cleanup."""
    volume_name = f"test-vol-{uuid.uuid4().hex[:8]}"

    flavors = openstack_client.flavor_list()
    assert flavors, "No flavors available"
    try:
        flavor = next(f for f in flavors if f.ram >= 1024).name
    except StopIteration:
        assert False, "No suitable flavor with >=1GB RAM found"

    resources = create_vm(
        openstack_client,
        testbed,
        ssh_runner,
        defer,
        flavor=flavor,
    )
    server_id = resources["server_id"]

    volume = openstack_client.volume_create(volume_name, size=1, timeout=180)
    defer(openstack_client.volume_delete, volume["id"])
    openstack_client.volume_attach(server_id, volume["id"])
    defer(openstack_client.volume_detach, server_id, volume["id"])

    return {
        **resources,
        "volume_id": volume["id"],
        "volume_name": volume_name,
    }


# ── Scenario 1: VM with volume can be spawned ──────────────────────────────────


@pytest.fixture
def spawn_vm_result() -> dict:
    return {}


@pytest.fixture
@when("I spawn a VM with a volume attached")
def spawn_vm_with_volume(
    demo_os_runner: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    spawn_vm_result: dict,
    defer: DeferStack,
):
    """Create a VM with a Cinder volume and a reachable floating IP."""
    if MOCK_MODE:
        spawn_vm_result.update(
            {
                "server_id": "mock-server",
                "volume_id": "mock-volume",
                "floating_ip": "192.0.2.1",
                "key_path": "/tmp/mock.pem",
                "primary_ip": "192.168.1.100",
            }
        )
        return
    resources = _create_vm_with_volume(demo_os_runner, testbed, ssh_runner, defer)
    spawn_vm_result.update(resources)


@then("the VM should be running")
def verify_vm_running(spawn_vm_result, demo_os_runner: OpenStackClient):
    """Verify the VM status is ACTIVE."""
    if MOCK_MODE:
        return
    server_id = spawn_vm_result["server_id"]
    with report.step(f"Checking VM {server_id} status"):
        status = demo_os_runner.server_status(server_id)
    assert status == "ACTIVE", f"Expected VM status ACTIVE, got {status!r}"
    report.note(f"VM {server_id} is ACTIVE")


@then("the volume should be accessible")
def verify_volume_accessible(spawn_vm_result, demo_os_runner: OpenStackClient):
    """Verify the volume is in-use (attached to the VM)."""
    if MOCK_MODE:
        return
    volume_id = spawn_vm_result["volume_id"]
    with report.step(f"Checking volume {volume_id} status"):
        status = demo_os_runner.volume_status(volume_id)
    assert status == "in-use", f"Expected volume status 'in-use', got {status!r}"
    report.note(f"Volume {volume_id} is in-use")


# ── Scenario 2: Storage remains available when one OSD host fails ──────────────


@pytest.fixture
def vm_resources() -> dict:
    return {}


@given("a VM with a volume attached")
def given_vm_with_volume(
    demo_os_runner: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    vm_resources: dict,
    defer: DeferStack,
):
    """Provision a VM with a volume and floating IP for the resilience test."""
    if MOCK_MODE:
        vm_resources.update(
            {
                "server_id": "mock-server",
                "volume_id": "mock-volume",
                "floating_ip": "192.0.2.1",
                "key_path": "/tmp/mock.pem",
                "primary_ip": "192.168.1.100",
            }
        )
        return
    resources = _create_vm_with_volume(demo_os_runner, testbed, ssh_runner, defer)
    vm_resources.update(resources)


@pytest.fixture
def osd_result() -> dict:
    return {}


@pytest.fixture
@when("I stop the OSD daemons on one host")
def stop_osd_on_host(
    testbed: TestbedConfig, ssh_runner: SSHRunner, osd_result: dict, defer: DeferStack
):
    """Stop microceph.osd on a non-primary storage node; restart on cleanup."""
    if MOCK_MODE:
        osd_result.update({"stopped": True, "host": "mock-host"})
        return

    storage_machines = [m for m in testbed.machines[1:] if "storage" in (m.roles or [])]
    if not storage_machines:
        pytest.skip("No secondary storage nodes available to simulate OSD failure")

    target = storage_machines[0]
    with report.step(f"Stopping microceph.osd on {target.hostname} ({target.ip})"):
        ssh_runner.run(target.ip, "sudo snap stop microceph.osd", attach_output=False)
    defer(
        ssh_runner.run,
        target.ip,
        "sudo snap restart microceph.osd",
        attach_output=False,
    )
    osd_result.update({"host": target.hostname, "ip": target.ip, "stopped": True})


@then("storage should remain available")
def verify_storage_available(testbed: TestbedConfig, ssh_runner: SSHRunner):
    """Assert the Ceph cluster is not in HEALTH_ERR state."""
    if MOCK_MODE:
        return
    primary_ip = testbed.primary_machine.ip
    with report.step("Checking Ceph cluster health"):
        result = ssh_runner.run(primary_ip, "sudo ceph health", attach_output=False)
        assert "HEALTH_ERR" not in result.stdout, (
            f"Ceph cluster is in HEALTH_ERR after OSD failure:\n{result.stdout}"
        )
        report.note(f"Ceph health: {result.stdout.strip()}")


@then("I should be able to read from the volume")
def verify_volume_read(vm_resources: dict, ssh_runner: SSHRunner):
    """Read from /dev/vdb on the VM to verify the volume is readable."""
    if MOCK_MODE:
        return
    floating_ip = vm_resources["floating_ip"]
    key_path = vm_resources["key_path"]
    with report.step(f"Reading from /dev/vdb on VM at {floating_ip}"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "sudo dd if=/dev/vdb of=/dev/null bs=1M count=1 status=none && echo ok",
            proxy_jump_host=vm_resources.get("proxy_jump_host"),
        )
        assert result.succeeded, (
            f"Read from /dev/vdb failed (rc={result.returncode}):\n{result.stderr}"
        )
        report.note("Volume read successful")


@then("I should be able to write to the volume")
def verify_volume_write(vm_resources: dict, ssh_runner: SSHRunner):
    """Write to /dev/vdb on the VM to verify the volume is writable."""
    if MOCK_MODE:
        return
    floating_ip = vm_resources["floating_ip"]
    key_path = vm_resources["key_path"]
    with report.step(f"Writing to /dev/vdb on VM at {floating_ip}"):
        result = vm_ssh(
            ssh_runner,
            floating_ip,
            key_path,
            "sudo dd if=/dev/zero of=/dev/vdb bs=1M count=1 status=none && echo ok",
            proxy_jump_host=vm_resources.get("proxy_jump_host"),
        )
        assert result.succeeded, (
            f"Write to /dev/vdb failed (rc={result.returncode}):\n{result.stderr}"
        )
        report.note("Volume write successful")
