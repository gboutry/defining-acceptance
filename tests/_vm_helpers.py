"""Shared VM creation helpers for acceptance test step definitions.

These functions are intentionally not pytest fixtures so they can be imported
by any conftest without creating scope or collection conflicts.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from defining_acceptance.clients.ssh import CommandResult, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.utils import DeferStack

if TYPE_CHECKING:
    from defining_acceptance.clients.openstack import OpenStackClient
    from defining_acceptance.testbed import TestbedConfig


def wait_for_vm_ssh(
    ssh_runner: SSHRunner,
    primary_ip: str,
    vm_ip: str,
    key_path: str,
    timeout: int = 120,
) -> None:
    """Poll until SSH becomes available on the VM via the primary node."""
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


def vm_ssh(
    ssh_runner: SSHRunner,
    primary_ip: str,
    floating_ip: str,
    key_path: str,
    command: str,
    timeout: int = 60,
) -> CommandResult:
    """Execute *command* inside a VM by proxying through the primary node."""
    ssh_cmd = (
        f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10"
        f" -i {key_path} ubuntu@{floating_ip} '{command}'"
    )
    return ssh_runner.run(primary_ip, ssh_cmd, timeout=timeout, attach_output=False)


def create_vm(
    openstack_client: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    defer: DeferStack,
    *,
    flavor: str | None = None,
    network_name: str | None = None,
    security_groups: list[str] | None = None,
    server_group_id: str | None = None,
    with_floating_ip: bool = True,
    poll_ssh: bool = True,
) -> dict:
    """Provision a VM and register a teardown finalizer.

    Returns a dict with keys:
        server_id, server_name, keypair_name, key_path, primary_ip,
        floating_ip (empty string if not requested), internal_ip, network_name.
    """
    uid = uuid.uuid4().hex[:8]
    keypair_name = f"test-key-{uid}"
    server_name = f"test-vm-{uid}"
    primary_ip = testbed.primary_machine.ip

    all_networks = openstack_client.network_list()
    assert all_networks, "No networks available — ensure the cloud is configured"
    images = openstack_client.image_list()
    assert images, "No images available"

    if flavor is None:
        flavors = openstack_client.flavor_list()
        assert flavors, "No flavors available"
        flavor = next(
            flavor
            for flavor in sorted(flavors, key=lambda f: f["RAM"])
            if flavor["RAM"] >= 1024 and "sev" not in flavor["Name"].lower()
        )["Name"]
    image = next(
        (i for i in images if "ubuntu" in i["Name"].lower()),
        images[0],
    )["ID"]

    if network_name is None:
        network_name = next(
            (n for n in all_networks if "external" not in n["Name"].lower()),
            all_networks[0],
        )["Name"]

    external_net = next(
        (n for n in all_networks if "external-network" == n["Name"].lower()),
        all_networks[0],
    )["Name"]

    with report.step(f"Creating keypair {keypair_name!r}"):
        private_key = openstack_client.keypair_create(keypair_name)
        defer(openstack_client.keypair_delete, keypair_name)
    key_path = f"/tmp/{keypair_name}.pem"
    ssh_runner.write_file(primary_ip, key_path, private_key)
    defer(ssh_runner.run, primary_ip, f"rm -f {key_path}", attach_output=False)
    ssh_runner.run(primary_ip, f"chmod 600 {key_path}", attach_output=False)

    server = openstack_client.server_create(
        server_name,
        flavor=flavor,
        image=image,
        network=network_name,
        key_name=keypair_name,
        security_groups=security_groups,
        server_group_id=server_group_id,
        timeout=300,
    )
    server_id = server["id"]
    defer(openstack_client.server_delete, server_id)

    # Extract the first fixed IP from any network.
    internal_ip = ""
    for net_addrs in server.get("addresses", {}).values():
        if net_addrs:
            internal_ip = net_addrs[0]
            break

    floating_ip = ""
    if with_floating_ip:
        fip = openstack_client.floating_ip_create(external_net)
        defer(openstack_client.floating_ip_delete, fip["floating_ip_address"])
        floating_ip = fip["floating_ip_address"]
        openstack_client.floating_ip_add(server_id, floating_ip)
        if poll_ssh:
            with report.step(f"Waiting for SSH on VM at {floating_ip}"):
                wait_for_vm_ssh(ssh_runner, primary_ip, floating_ip, key_path)

    resources: dict = {
        "server_id": server_id,
        "server_name": server_name,
        "keypair_name": keypair_name,
        "key_path": key_path,
        "primary_ip": primary_ip,
        "floating_ip": floating_ip,
        "internal_ip": internal_ip,
        "network_name": network_name,
    }

    return resources
