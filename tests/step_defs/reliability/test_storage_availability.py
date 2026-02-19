"""Step definitions for storage availability reliability tests."""

import os
import time
import uuid
from contextlib import suppress

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report

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


def _wait_for_ssh(
    ssh_runner,
    primary_ip: str,
    vm_ip: str,
    key_path: str,
    timeout: int = 120,
) -> None:
    """Poll until SSH is reachable on the VM proxied through the primary node."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = ssh_runner.run(
            primary_ip,
            (
                f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5"
                f" -i {key_path} ubuntu@{vm_ip} 'echo ok'"
            ),
            timeout=30,
            attach_output=False,
        )
        if result.succeeded:
            return
        time.sleep(5)
    raise TimeoutError(
        f"SSH to VM at {vm_ip} did not become available within {timeout}s"
    )


def _create_vm_with_volume(openstack_client, testbed, ssh_runner, request) -> dict:
    """Create a VM with a volume attached and a floating IP; register cleanup."""
    uid = uuid.uuid4().hex[:8]
    keypair_name = f"test-key-{uid}"
    server_name = f"test-vm-{uid}"
    volume_name = f"test-vol-{uid}"
    primary_ip = testbed.primary_machine.ip

    flavors = openstack_client.flavor_list()
    assert flavors, "No flavors available"
    images = openstack_client.image_list()
    assert images, "No images available"
    networks = openstack_client.network_list()
    assert networks, "No networks available"

    flavor = flavors[0]["Name"]
    image = next(
        (i for i in images if "ubuntu" in i["Name"].lower()),
        images[0],
    )["ID"]
    network = next(
        (n for n in networks if "external" not in n["Name"].lower()),
        networks[0],
    )["Name"]
    external_net = next(
        (n for n in networks if "external" in n["Name"].lower()),
        networks[0],
    )["Name"]

    # Create keypair; OpenStack generates the private key, returned only once.
    with report.step(f"Creating keypair {keypair_name!r}"):
        kp = openstack_client.keypair_create(keypair_name)
    private_key = kp.get("private_key") or kp.get("Private Key", "")
    key_path = f"/tmp/{keypair_name}.pem"
    ssh_runner.write_file(primary_ip, key_path, private_key)
    ssh_runner.run(primary_ip, f"chmod 600 {key_path}", attach_output=False)

    server = openstack_client.server_create(
        server_name,
        flavor=flavor,
        image=image,
        network=network,
        key_name=keypair_name,
        timeout=300,
    )
    server_id = server["id"]

    volume = openstack_client.volume_create(volume_name, size=1, timeout=120)
    volume_id = volume["id"]
    openstack_client.volume_attach(server_id, volume_id)

    fip = openstack_client.floating_ip_create(external_net)
    floating_ip = fip["floating_ip_address"]
    openstack_client.floating_ip_add(server_id, floating_ip)

    with report.step(f"Waiting for SSH on VM at {floating_ip}"):
        _wait_for_ssh(ssh_runner, primary_ip, floating_ip, key_path)

    resources = {
        "server_id": server_id,
        "server_name": server_name,
        "volume_id": volume_id,
        "volume_name": volume_name,
        "keypair_name": keypair_name,
        "floating_ip": floating_ip,
        "key_path": key_path,
        "primary_ip": primary_ip,
    }

    def _cleanup() -> None:
        with suppress(Exception):
            openstack_client.floating_ip_delete(floating_ip)
        with suppress(Exception):
            openstack_client.volume_detach(server_id, volume_id)
        with suppress(Exception):
            openstack_client.server_delete(server_id)
        with suppress(Exception):
            openstack_client.volume_delete(volume_id)
        with suppress(Exception):
            openstack_client.keypair_delete(keypair_name)
        with suppress(Exception):
            ssh_runner.run(primary_ip, f"rm -f {key_path}", attach_output=False)

    request.addfinalizer(_cleanup)
    return resources


def _vm_ssh(
    ssh_runner,
    primary_ip: str,
    floating_ip: str,
    key_path: str,
    command: str,
) -> CommandResult:
    """Run a command on the VM by proxying through the primary node."""
    ssh_cmd = (
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10"
        f" -i {key_path} ubuntu@{floating_ip} '{command}'"
    )
    return ssh_runner.run(primary_ip, ssh_cmd, timeout=60, attach_output=False)


# ── Scenario 1: VM with volume can be spawned ──────────────────────────────────


@pytest.fixture
def spawn_vm_result() -> dict:
    return {}


@pytest.fixture
@when("I spawn a VM with a volume attached")
def spawn_vm_with_volume(
    openstack_client, testbed, ssh_runner, spawn_vm_result, request
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
    resources = _create_vm_with_volume(openstack_client, testbed, ssh_runner, request)
    spawn_vm_result.update(resources)


@then("the VM should be running")
def verify_vm_running(spawn_vm_result, openstack_client):
    """Verify the VM status is ACTIVE."""
    if MOCK_MODE:
        return
    server_id = spawn_vm_result["server_id"]
    with report.step(f"Checking VM {server_id} status"):
        status = openstack_client.server_status(server_id)
    assert status == "ACTIVE", f"Expected VM status ACTIVE, got {status!r}"
    report.note(f"VM {server_id} is ACTIVE")


@then("the volume should be accessible")
def verify_volume_accessible(spawn_vm_result, openstack_client):
    """Verify the volume is in-use (attached to the VM)."""
    if MOCK_MODE:
        return
    volume_id = spawn_vm_result["volume_id"]
    with report.step(f"Checking volume {volume_id} status"):
        status = openstack_client.volume_status(volume_id)
    assert status == "in-use", f"Expected volume status 'in-use', got {status!r}"
    report.note(f"Volume {volume_id} is in-use")


# ── Scenario 2: Storage remains available when one OSD host fails ──────────────


@pytest.fixture
def vm_resources() -> dict:
    return {}


@given("a VM with a volume attached")
def given_vm_with_volume(openstack_client, testbed, ssh_runner, vm_resources, request):
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
    resources = _create_vm_with_volume(openstack_client, testbed, ssh_runner, request)
    vm_resources.update(resources)


@pytest.fixture
def osd_result() -> dict:
    return {}


@pytest.fixture
@when("I stop the OSD daemons on one host")
def stop_osd_on_host(testbed, ssh_runner, osd_result, request):
    """Stop microceph.osd on a non-primary storage node; restart on cleanup."""
    if MOCK_MODE:
        osd_result.update({"stopped": True, "host": "mock-host"})
        return

    storage_machines = [m for m in testbed.machines[1:] if "storage" in (m.roles or [])]
    if not storage_machines:
        pytest.skip("No secondary storage nodes available to simulate OSD failure")

    target = storage_machines[0]
    with report.step(f"Stopping microceph.osd on {target.hostname} ({target.ip})"):
        ssh_runner.run(
            target.ip, "sudo snap stop microceph.osd", attach_output=False
        )
    osd_result.update({"host": target.hostname, "ip": target.ip, "stopped": True})

    def _restart() -> None:
        with suppress(Exception):
            ssh_runner.run(
                target.ip,
                "sudo snap restart microceph.osd",
                attach_output=False,
            )

    request.addfinalizer(_restart)


@then("storage should remain available")
def verify_storage_available(testbed, ssh_runner):
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
def verify_volume_read(vm_resources, ssh_runner):
    """Read from /dev/vdb on the VM to verify the volume is readable."""
    if MOCK_MODE:
        return
    floating_ip = vm_resources["floating_ip"]
    key_path = vm_resources["key_path"]
    primary_ip = vm_resources["primary_ip"]
    with report.step(f"Reading from /dev/vdb on VM at {floating_ip}"):
        result = _vm_ssh(
            ssh_runner,
            primary_ip,
            floating_ip,
            key_path,
            "sudo dd if=/dev/vdb of=/dev/null bs=1M count=1 status=none && echo ok",
        )
        assert result.succeeded, (
            f"Read from /dev/vdb failed (rc={result.returncode}):\n{result.stderr}"
        )
        report.note("Volume read successful")


@then("I should be able to write to the volume")
def verify_volume_write(vm_resources, ssh_runner):
    """Write to /dev/vdb on the VM to verify the volume is writable."""
    if MOCK_MODE:
        return
    floating_ip = vm_resources["floating_ip"]
    key_path = vm_resources["key_path"]
    primary_ip = vm_resources["primary_ip"]
    with report.step(f"Writing to /dev/vdb on VM at {floating_ip}"):
        result = _vm_ssh(
            ssh_runner,
            primary_ip,
            floating_ip,
            key_path,
            "sudo dd if=/dev/zero of=/dev/vdb bs=1M count=1 status=none && echo ok",
        )
        assert result.succeeded, (
            f"Write to /dev/vdb failed (rc={result.returncode}):\n{result.stderr}"
        )
        report.note("Volume write successful")
