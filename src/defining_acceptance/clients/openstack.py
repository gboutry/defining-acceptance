"""OpenStack client backed by the openstacksdk Python library."""

from __future__ import annotations

import time
from typing import cast

import openstack
import openstack.connection
from openstack.block_storage.v3._proxy import Proxy as BlockStorageProxy
from openstack.block_storage.v3.volume import Volume
from openstack.compute.v2._proxy import Proxy as ComputeProxy
from openstack.compute.v2.flavor import Flavor
from openstack.compute.v2.keypair import Keypair
from openstack.compute.v2.server import Server
from openstack.compute.v2.server_group import ServerGroup
from openstack.identity.v3._proxy import Proxy as IdentityProxy
from openstack.identity.v3.endpoint import Endpoint
from openstack.image.v2._proxy import Proxy as ImageProxy
from openstack.image.v2.image import Image
from openstack.network.v2._proxy import Proxy as NetworkProxy
from openstack.network.v2.floating_ip import FloatingIP
from openstack.network.v2.network import Network
from openstack.network.v2.security_group import SecurityGroup
from openstack.network.v2.security_group_rule import SecurityGroupRule


class OpenStackClient:
    """Interact with OpenStack services using the Python SDK."""

    def __init__(self, connection: openstack.connection.Connection) -> None:
        self._conn = connection
        self._compute: ComputeProxy = cast(ComputeProxy, connection.compute)
        self._identity: IdentityProxy = cast(IdentityProxy, connection.identity)
        self._network: NetworkProxy = cast(NetworkProxy, connection.network)
        self._block_storage: BlockStorageProxy = cast(
            BlockStorageProxy, connection.block_storage
        )
        self._image: ImageProxy = cast(ImageProxy, connection.image)

    # ── Catalog validation ────────────────────────────────────────────────────

    def endpoint_list(self) -> list[Endpoint]:
        return list(self._identity.endpoints())

    # ── Compute (server) ──────────────────────────────────────────────────────

    def server_create(
        self,
        name: str,
        flavor: str,
        image: str,
        network: str,
        key_name: str | None = None,
        security_groups: list[str] | None = None,
        server_group_id: str | None = None,
        wait: bool = True,
        timeout: int = 300,
    ) -> Server:
        attrs: dict = {
            "name": name,
            "flavor_id": flavor,
            "image_id": image,
            "networks": [{"uuid": network}],
        }
        if key_name is not None:
            attrs["key_name"] = key_name
        if security_groups:
            attrs["security_groups"] = [{"name": sg} for sg in security_groups]
        if server_group_id is not None:
            attrs["scheduler_hints"] = {"group": server_group_id}

        server = self._compute.create_server(**attrs)
        if wait:
            server = self._compute.wait_for_server(server, wait=timeout)
        return server

    def server_show(self, name_or_id: str) -> Server:
        return self._compute.get_server(name_or_id)

    def server_delete(self, name_or_id: str, wait: bool = True) -> None:
        self._compute.delete_server(name_or_id)
        if wait:
            self._compute.wait_for_delete(self._compute.get_server(name_or_id))

    def server_list(self) -> list[Server]:
        return list(self._compute.servers())

    def server_status(self, name_or_id: str) -> str:
        return self.server_show(name_or_id).status

    def server_reboot(
        self,
        name_or_id: str,
        hard: bool = False,
        wait: bool = True,
        timeout: int = 120,
    ) -> None:
        reboot_type = "HARD" if hard else "SOFT"
        self._compute.reboot_server(name_or_id, reboot_type)
        if wait:
            self.wait_for_server_status(name_or_id, timeout=timeout)

    def wait_for_server_status(
        self,
        name_or_id: str,
        status: str = "ACTIVE",
        timeout: int = 300,
    ) -> Server:
        """Poll server status until it matches *status* or *timeout* elapses."""
        deadline = time.monotonic() + timeout
        while True:
            server = self.server_show(name_or_id)
            if server.status == status:
                return server
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Server {name_or_id!r} did not reach status {status!r} "
                    f"within {timeout}s. Current: {server.status!r}"
                )
            time.sleep(10)

    def server_add_security_group(self, server: str, security_group: str) -> None:
        """Add a security group to a server."""
        self._compute.add_security_group_to_server(server, security_group)

    def server_remove_security_group(self, server: str, security_group: str) -> None:
        """Remove a security group from a server."""
        self._compute.remove_security_group_from_server(server, security_group)

    # ── Server groups ─────────────────────────────────────────────────────────

    def server_group_create(self, name: str, policy: str) -> ServerGroup:
        """Create a server group (e.g. policy='soft-affinity')."""
        return self._compute.create_server_group(name=name, policy=policy)

    def server_group_delete(self, name_or_id: str) -> None:
        self._compute.delete_server_group(name_or_id)

    # ── Volume ────────────────────────────────────────────────────────────────

    def volume_create(
        self,
        name: str,
        size: int,
        wait: bool = True,
        timeout: int = 120,
    ) -> Volume:
        volume = self._block_storage.create_volume(name=name, size=size)
        if wait:
            volume = self._block_storage.wait_for_status(
                volume, status="available", wait=timeout
            )
        return volume

    def volume_show(self, name_or_id: str) -> Volume:
        return self._block_storage.get_volume(name_or_id)

    def volume_delete(self, name_or_id: str) -> None:
        self._block_storage.delete_volume(name_or_id)

    def volume_status(self, name_or_id: str) -> str:
        return self.volume_show(name_or_id).status

    def volume_attach(self, server: str, volume: str) -> None:
        self._compute.create_volume_attachment(server, volume_id=volume)

    def volume_detach(self, server: str, volume: str) -> None:
        # Find the attachment for this volume on this server
        for attachment in self._compute.volume_attachments(server):
            if attachment.volume_id == volume:
                self._compute.delete_volume_attachment(attachment.id, server)
                return
        raise ValueError(f"Volume {volume!r} is not attached to server {server!r}")

    # ── Network ───────────────────────────────────────────────────────────────

    def floating_ip_create(self, network: str) -> FloatingIP:
        return self._network.create_ip(floating_network_id=network)

    def floating_ip_add(self, server: str, floating_ip: str) -> None:
        self._compute.add_floating_ip_to_server(server, floating_ip)

    def floating_ip_delete(self, floating_ip: str) -> None:
        self._network.delete_ip(floating_ip)

    def network_list(self) -> list[Network]:
        return list(self._network.networks())

    def security_group_list(self) -> list[SecurityGroup]:
        return list(self._network.security_groups())

    def security_group_create(self, name: str, description: str = "") -> SecurityGroup:
        return self._network.create_security_group(name=name, description=description)

    def security_group_delete(self, name_or_id: str) -> None:
        self._network.delete_security_group(name_or_id)

    def security_group_rule_list(self, security_group: str) -> list[SecurityGroupRule]:
        return list(
            self._network.security_group_rules(security_group_id=security_group)
        )

    def security_group_rule_create(
        self,
        group: str,
        direction: str = "ingress",
        protocol: str | None = None,
        dst_port: str | None = None,
        remote_ip: str | None = None,
        ethertype: str = "IPv4",
    ) -> SecurityGroupRule:
        attrs: dict = {
            "security_group_id": group,
            "direction": direction,
            "ethertype": ethertype,
        }
        if protocol:
            attrs["protocol"] = protocol
        if dst_port:
            # The SDK expects port_range_min and port_range_max
            if ":" in dst_port:
                low, high = dst_port.split(":", 1)
                attrs["port_range_min"] = int(low)
                attrs["port_range_max"] = int(high)
            else:
                attrs["port_range_min"] = int(dst_port)
                attrs["port_range_max"] = int(dst_port)
        if remote_ip:
            attrs["remote_ip_prefix"] = remote_ip
        return self._network.create_security_group_rule(**attrs)

    def security_group_rule_delete(self, rule_id: str) -> None:
        self._network.delete_security_group_rule(rule_id)

    # ── Neutron resources ─────────────────────────────────────────────────────

    def network_create(self, name: str) -> Network:
        return self._network.create_network(name=name)

    def network_delete(self, name_or_id: str) -> None:
        self._network.delete_network(name_or_id)

    def subnet_create(self, name: str, network: str, cidr: str):
        return self._network.create_subnet(name=name, network_id=network, cidr=cidr)

    def subnet_delete(self, name_or_id: str) -> None:
        self._network.delete_subnet(name_or_id)

    def router_create(self, name: str, external_gateway: str | None = None):
        attrs: dict = {"name": name}
        if external_gateway:
            attrs["external_gateway_info"] = {"network_id": external_gateway}
        return self._network.create_router(**attrs)

    def router_delete(self, name_or_id: str) -> None:
        self._network.delete_router(name_or_id)

    def router_add_subnet(self, router: str, subnet: str) -> None:
        self._network.add_interface_to_router(router, subnet_id=subnet)

    def router_remove_subnet(self, router: str, subnet: str) -> None:
        self._network.remove_interface_from_router(router, subnet_id=subnet)

    # ── Keypair ───────────────────────────────────────────────────────────────

    def keypair_create(self, name: str) -> Keypair:
        return self._compute.create_keypair(name=name)

    def keypair_delete(self, name: str) -> None:
        self._compute.delete_keypair(name)

    # ── Image ─────────────────────────────────────────────────────────────────

    def image_list(self) -> list[Image]:
        return list(self._image.images())

    def image_show(self, name_or_id: str) -> Image:
        return self._image.get_image(name_or_id)

    # ── Flavor ────────────────────────────────────────────────────────────────

    def flavor_list(self) -> list[Flavor]:
        return list(self._compute.flavors())
