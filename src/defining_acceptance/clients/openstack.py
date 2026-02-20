"""OpenStack CLI client executed via SSH on the primary control node."""

from __future__ import annotations

import json
import time
from typing import Any

from defining_acceptance.clients.ssh import CommandResult, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig


class OpenStackClient:
    def __init__(
        self,
        ssh: SSHRunner,
        machine: MachineConfig,
    ) -> None:
        self._ssh = ssh
        self._machine = machine

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run(self, subcommand: str, timeout: int = 120) -> CommandResult:
        return self._ssh.run(self._machine.ip, f"openstack {subcommand}", timeout)

    def _run_json(self, subcommand: str, timeout: int = 120) -> Any:
        result = self._run(f"{subcommand} -f json", timeout)
        result.check()
        return json.loads(result.stdout)

    # ── Catalog validation ────────────────────────────────────────────────────

    def endpoint_list(self) -> list[dict]:
        return self._run_json("endpoint list")

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
    ) -> dict:
        cmd = (
            f"server create {name}"
            f" --flavor {flavor}"
            f" --image {image}"
            f" --network {network}"
        )
        if key_name is not None:
            cmd += f" --key-name {key_name}"
        if security_groups:
            for sg in security_groups:
                cmd += f" --security-group {sg}"
        if server_group_id is not None:
            cmd += f" --hint group={server_group_id}"
        if wait:
            cmd += " --wait"
        with report.step(f"Create server {name!r}"):
            return self._run_json(cmd, timeout)

    def server_show(self, name_or_id: str) -> dict:
        return self._run_json(f"server show {name_or_id}")

    def server_delete(self, name_or_id: str, wait: bool = True) -> CommandResult:
        cmd = f"server delete {name_or_id}"
        if wait:
            cmd += " --wait"
        with report.step(f"Delete server {name_or_id!r}"):
            return self._run(cmd).check()

    def server_list(self) -> list[dict]:
        return self._run_json("server list")

    def server_status(self, name_or_id: str) -> str:
        return self.server_show(name_or_id)["status"]

    def server_reboot(
        self,
        name_or_id: str,
        hard: bool = False,
        wait: bool = True,
        timeout: int = 120,
    ) -> CommandResult:
        cmd = f"server reboot {name_or_id}"
        if hard:
            cmd += " --hard"
        if wait:
            cmd += " --wait"
        with report.step(f"Reboot server {name_or_id!r}"):
            return self._run(cmd, timeout).check()

    def wait_for_server_status(
        self,
        name_or_id: str,
        status: str = "ACTIVE",
        timeout: int = 300,
    ) -> dict:
        """Poll server status until it matches *status* or *timeout* elapses."""
        deadline = time.monotonic() + timeout
        while True:
            server = self.server_show(name_or_id)
            if server["status"] == status:
                return server
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Server {name_or_id!r} did not reach status {status!r} "
                    f"within {timeout}s. Current: {server['status']!r}"
                )
            time.sleep(10)

    # ── Server groups ─────────────────────────────────────────────────────────

    def server_group_create(self, name: str, policy: str) -> dict:
        """Create a server group (e.g. policy='soft-affinity')."""
        return self._run_json(f"server group create {name} --policy {policy}")

    def server_group_delete(self, name_or_id: str) -> CommandResult:
        return self._run(f"server group delete {name_or_id}").check()

    # ── Volume ────────────────────────────────────────────────────────────────

    def volume_create(
        self,
        name: str,
        size: int,
        wait: bool = True,
        timeout: int = 120,
    ) -> dict:
        cmd = f"volume create {name} --size {size}"
        if wait:
            cmd += " --wait"
        with report.step(f"Create volume {name!r}"):
            return self._run_json(cmd, timeout)

    def volume_show(self, name_or_id: str) -> dict:
        return self._run_json(f"volume show {name_or_id}")

    def volume_delete(self, name_or_id: str) -> CommandResult:
        with report.step(f"Delete volume {name_or_id!r}"):
            return self._run(f"volume delete {name_or_id}").check()

    def volume_status(self, name_or_id: str) -> str:
        return self.volume_show(name_or_id)["status"]

    def volume_attach(self, server: str, volume: str) -> CommandResult:
        with report.step(f"Attach volume {volume!r} to server {server!r}"):
            return self._run(f"server add volume {server} {volume}").check()

    def volume_detach(self, server: str, volume: str) -> CommandResult:
        with report.step(f"Detach volume {volume!r} from server {server!r}"):
            return self._run(f"server remove volume {server} {volume}").check()

    # ── Network ───────────────────────────────────────────────────────────────

    def floating_ip_create(self, network: str) -> dict:
        with report.step(f"Create floating IP on network {network!r}"):
            return self._run_json(f"floating ip create {network}")

    def floating_ip_add(self, server: str, floating_ip: str) -> CommandResult:
        with report.step(f"Add floating IP {floating_ip!r} to server {server!r}"):
            return self._run(f"server add floating ip {server} {floating_ip}").check()

    def floating_ip_delete(self, floating_ip: str) -> CommandResult:
        return self._run(f"floating ip delete {floating_ip}").check()

    def network_list(self) -> list[dict]:
        return self._run_json("network list")

    def security_group_list(self) -> list[dict]:
        return self._run_json("security group list")

    def security_group_create(self, name: str, description: str = "") -> dict:
        cmd = f"security group create {name}"
        if description:
            cmd += f" --description '{description}'"
        return self._run_json(cmd)

    def security_group_delete(self, name_or_id: str) -> CommandResult:
        return self._run(f"security group delete {name_or_id}").check()

    def security_group_rule_list(self, security_group: str) -> list[dict]:
        return self._run_json(
            f"security group rule list --security-group {security_group}"
        )

    def security_group_rule_create(
        self,
        group: str,
        direction: str = "ingress",
        protocol: str | None = None,
        dst_port: str | None = None,
        remote_ip: str | None = None,
        ethertype: str = "IPv4",
    ) -> dict:
        cmd = (
            f"security group rule create {group}"
            f" --direction {direction}"
            f" --ethertype {ethertype}"
        )
        if protocol:
            cmd += f" --protocol {protocol}"
        if dst_port:
            cmd += f" --dst-port {dst_port}"
        if remote_ip:
            cmd += f" --remote-ip {remote_ip}"
        return self._run_json(cmd)

    def security_group_rule_delete(self, rule_id: str) -> CommandResult:
        return self._run(f"security group rule delete {rule_id}").check()

    # ── Neutron resources ─────────────────────────────────────────────────────

    def network_create(self, name: str) -> dict:
        return self._run_json(f"network create {name}")

    def network_delete(self, name_or_id: str) -> CommandResult:
        return self._run(f"network delete {name_or_id}").check()

    def subnet_create(self, name: str, network: str, cidr: str) -> dict:
        return self._run_json(
            f"subnet create {name} --network {network} --subnet-range {cidr}"
        )

    def subnet_delete(self, name_or_id: str) -> CommandResult:
        return self._run(f"subnet delete {name_or_id}").check()

    def router_create(self, name: str, external_gateway: str | None = None) -> dict:
        cmd = f"router create {name}"
        if external_gateway:
            cmd += f" --external-gateway {external_gateway}"
        return self._run_json(cmd)

    def router_delete(self, name_or_id: str) -> CommandResult:
        return self._run(f"router delete {name_or_id}").check()

    def router_add_subnet(self, router: str, subnet: str) -> CommandResult:
        return self._run(f"router add subnet {router} {subnet}").check()

    def router_remove_subnet(self, router: str, subnet: str) -> CommandResult:
        return self._run(f"router remove subnet {router} {subnet}").check()

    # ── Keypair ───────────────────────────────────────────────────────────────

    def keypair_create(self, name: str, public_key: str | None = None) -> str:
        cmd = f"keypair create {name}"
        remote_path: str | None = None
        if public_key is not None:
            remote_path = f"/tmp/keypair-{name}.pub"
            self._ssh.write_file(self._machine.ip, remote_path, public_key)
            cmd += f" --public-key {remote_path}"
        with report.step(f"Create keypair {name!r}"):
            try:
                ret = self._run(cmd)
                ret.check()
                return ret.stdout.strip()
            finally:
                if remote_path is not None:
                    self._run(f"rm -f {remote_path}")

    def keypair_delete(self, name: str) -> CommandResult:
        return self._run(f"keypair delete {name}").check()

    # ── Image ─────────────────────────────────────────────────────────────────

    def image_list(self) -> list[dict]:
        return self._run_json("image list")

    def image_show(self, name_or_id: str) -> dict:
        return self._run_json(f"image show {name_or_id}")

    # ── Flavor ────────────────────────────────────────────────────────────────

    def flavor_list(self) -> list[dict]:
        return self._run_json("flavor list")
