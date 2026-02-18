"""OpenStack CLI client executed via SSH on the primary control node."""
from __future__ import annotations

import json
from typing import Any

from defining_acceptance.clients.ssh import CommandResult, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig


class OpenStackClient:
    def __init__(
        self,
        ssh: SSHRunner,
        primary: MachineConfig,
        openrc_path: str = "demo-openrc",
    ) -> None:
        self._ssh = ssh
        self._primary = primary
        self._openrc = openrc_path

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run(self, subcommand: str, timeout: int = 120) -> CommandResult:
        command = f"source {self._openrc} && openstack {subcommand}"
        return self._ssh.run(self._primary.ip, command, timeout)

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

    # ── Keypair ───────────────────────────────────────────────────────────────

    def keypair_create(self, name: str, public_key: str | None = None) -> dict:
        cmd = f"keypair create {name}"
        remote_path: str | None = None
        if public_key is not None:
            remote_path = f"/tmp/keypair-{name}.pub"
            self._ssh.write_file(self._primary.ip, remote_path, public_key)
            cmd += f" --public-key {remote_path}"
        with report.step(f"Create keypair {name!r}"):
            try:
                return self._run_json(cmd)
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
