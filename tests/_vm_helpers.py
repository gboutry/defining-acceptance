"""Shared VM creation helpers for acceptance test step definitions.

These functions are intentionally not pytest fixtures so they can be imported
by any conftest without creating scope or collection conflicts.
"""

from __future__ import annotations

import os
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from defining_acceptance.clients.ssh import CommandResult, SSHError, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.utils import DeferStack

if TYPE_CHECKING:
    from defining_acceptance.clients.openstack import OpenStackClient
    from defining_acceptance.testbed import TestbedConfig


def wait_for_vm_ssh(
    ssh_runner: SSHRunner,
    vm_ip: str,
    key_path: str,
    timeout: int = 120,
    proxy_jump_host: str | None = None,
) -> None:
    """Poll until SSH becomes available on the VM."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = ssh_runner.run(
                vm_ip,
                command="echo ok",
                timeout=30,
                attach_output=False,
                proxy_jump_host=proxy_jump_host,
                private_key_override=key_path,
            )
            if result.succeeded:
                return
        except SSHError:
            # Ignore SSH errors, which likely indicate that the VM is not ready yet.
            continue
        time.sleep(5)
    raise TimeoutError(
        f"SSH to VM at {vm_ip} did not become available within {timeout}s"
    )


def vm_ssh(
    ssh_runner: SSHRunner,
    floating_ip: str,
    key_path: str,
    command: str,
    timeout: int = 60,
    proxy_jump_host: str | None = None,
    attach_output: bool = False,
) -> CommandResult:
    """Execute *command* inside a VM."""
    return ssh_runner.run(
        floating_ip,
        command,
        timeout=timeout,
        attach_output=attach_output,
        proxy_jump_host=proxy_jump_host,
        private_key_override=key_path,
    )


def ensure_iperf3_installed(
    ssh_runner: SSHRunner,
    resources: dict,
    *,
    update_timeout: int = 300,
    install_timeout: int = 300,
) -> None:
    """Ensure iperf3 is installed on a VM with visible apt output."""
    with report.step("Updating apt package index"):
        vm_ssh(
            ssh_runner,
            resources["floating_ip"],
            resources["key_path"],
            "sudo apt-get update",
            timeout=update_timeout,
            proxy_jump_host=resources.get("proxy_jump_host"),
            attach_output=True,
        ).check()

    with report.step("Installing iperf3"):
        vm_ssh(
            ssh_runner,
            resources["floating_ip"],
            resources["key_path"],
            "sudo apt-get install -y iperf3",
            timeout=install_timeout,
            proxy_jump_host=resources.get("proxy_jump_host"),
            attach_output=True,
        ).check()


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
            f
            for f in sorted(flavors, key=lambda f: f.ram)
            if f.ram >= 1024 and "sev" not in f.name.lower()
        ).id
    image = next(
        (i for i in images if "ubuntu" in i.name.lower()),
        images[0],
    ).id

    if network_name is None:
        network_name = next(
            (n for n in all_networks if "external" not in n.name.lower()),
            all_networks[0],
        ).id

    external_net = next(
        (n for n in all_networks if "external-network" == n.name.lower()),
        all_networks[0],
    ).id

    with report.step(f"Creating keypair {keypair_name!r}"):
        keypair = openstack_client.keypair_create(keypair_name)
        defer(openstack_client.keypair_delete, keypair_name)
    key_path = str(Path(tempfile.gettempdir()) / f"{keypair_name}.pem")
    Path(key_path).write_text(keypair.private_key)
    os.chmod(key_path, stat.S_IRUSR)
    defer(os.remove, key_path)

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
    server_id = server.id
    defer(openstack_client.server_delete, server_id)

    # Extract the first fixed IP from any network.
    internal_ip = ""
    for net_addrs in (server.addresses or {}).values():
        if net_addrs:
            internal_ip = net_addrs[0]["addr"]
            break

    floating_ip = ""
    if with_floating_ip:
        fip = openstack_client.floating_ip_create(external_net)
        defer(openstack_client.floating_ip_delete, fip.floating_ip_address)
        floating_ip = fip.floating_ip_address
        openstack_client.floating_ip_add(server_id, floating_ip)
        if poll_ssh:
            proxy_jump_host = testbed.ssh.proxy_jump if testbed.ssh else None
            with report.step(f"Waiting for SSH on VM at {floating_ip}"):
                wait_for_vm_ssh(
                    ssh_runner,
                    floating_ip,
                    key_path,
                    proxy_jump_host=proxy_jump_host,
                )

    resources: dict = {
        "server_id": server_id,
        "server_name": server_name,
        "keypair_name": keypair_name,
        "key_path": key_path,
        "primary_ip": primary_ip,
        "floating_ip": floating_ip,
        "internal_ip": internal_ip,
        "network_name": network_name,
        "proxy_jump_host": testbed.ssh.proxy_jump if testbed.ssh else None,
    }

    return resources
