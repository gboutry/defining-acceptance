"""High-level wrapper around the sunbeam CLI executed via SSH."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from defining_acceptance.clients.ssh import CommandResult, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig


class SunbeamClient:
    """Execute sunbeam CLI commands on a remote machine via SSH."""

    _REMOTE_MANIFEST_PATH = "/home/ubuntu/manifest.yaml"
    _SNAP_MANIFEST_ROOT = "/snap/openstack/current/etc/manifests"

    def __init__(self, ssh: SSHRunner) -> None:
        self._ssh = ssh

    def _prepare_remote_manifest(
        self,
        machine: MachineConfig,
        manifest_path: str | None,
        *,
        overlay_with_snap_manifest: bool = False,
        snap_manifest_channel: str | None = None,
    ) -> str | None:
        """Upload (or render) a manifest file and return its remote path."""
        if manifest_path is None:
            return None

        local_manifest_path = Path(manifest_path).expanduser().resolve(strict=False)
        if not local_manifest_path.is_file():
            raise FileNotFoundError(f"Manifest file not found: {local_manifest_path}")

        if overlay_with_snap_manifest:
            if not snap_manifest_channel:
                raise ValueError(
                    "deployment.channel must be set when using deployment.manifest "
                    "as an overlay"
                )
            track, risk = self._parse_track_and_risk(snap_manifest_channel)
            base_manifest_path = f"{self._SNAP_MANIFEST_ROOT}/{track}/{risk}.yml"
            with report.step(f"Read snap manifest from {base_manifest_path}"):
                base_result = self._ssh.run(
                    machine.ip, f"sudo cat '{base_manifest_path}'"
                )
                base_result.check()

            base_manifest = yaml.safe_load(base_result.stdout) or {}
            overlay_manifest = (
                yaml.safe_load(local_manifest_path.read_text(encoding="utf-8")) or {}
            )
            if not isinstance(base_manifest, dict):
                raise ValueError(
                    f"Snap manifest at {base_manifest_path} must be a YAML mapping"
                )
            if not isinstance(overlay_manifest, dict):
                raise ValueError("deployment.manifest overlay must be a YAML mapping")

            merged_manifest = self._deep_merge(base_manifest, overlay_manifest)
            rendered_manifest = yaml.safe_dump(merged_manifest, sort_keys=False)
            with report.step(f"Upload merged manifest to {machine.hostname}"):
                self._ssh.write_file(
                    machine.ip,
                    self._REMOTE_MANIFEST_PATH,
                    rendered_manifest,
                )
            return self._REMOTE_MANIFEST_PATH

        with report.step(f"Upload manifest to {machine.hostname}"):
            self._ssh.upload_file(
                machine.ip,
                local_manifest_path,
                self._REMOTE_MANIFEST_PATH,
            )

        return self._REMOTE_MANIFEST_PATH

    @staticmethod
    def _parse_track_and_risk(channel: str) -> tuple[str, str]:
        parts = channel.split("/")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"Invalid deployment.channel {channel!r}; expected format <track>/<risk>"
            )
        return parts[0], parts[1]

    @classmethod
    def _deep_merge(cls, base: Any, overlay: Any) -> Any:
        if isinstance(base, dict) and isinstance(overlay, dict):
            merged: dict[Any, Any] = dict(base)
            for key, value in overlay.items():
                if key in merged:
                    merged[key] = cls._deep_merge(merged[key], value)
                else:
                    merged[key] = value
            return merged
        return overlay

    def install_snap(
        self,
        machine: MachineConfig,
        channel: str | None = None,
        revision: int | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        """Install the openstack snap on the given machine.

        Does not call .check() because the snap may already be installed,
        in which case snap returns a non-zero exit code with "already installed"
        in stdout.
        """
        cmd = "sudo snap install openstack"
        if channel is not None:
            cmd += f" --channel {channel}"
        if revision is not None:
            cmd += f" --revision {revision}"
        label = f"channel={channel!r}" if channel else ""
        if revision is not None:
            label = f"{label} revision={revision}" if label else f"revision={revision}"
        with report.step(f"Install openstack snap ({label})"):
            result = self._ssh.run(machine.ip, cmd, timeout=timeout)
        return result

    def prepare_node(
        self,
        machine: MachineConfig,
        bootstrap: bool = False,
        client: bool = False,
        timeout: int = 600,
    ) -> CommandResult:
        """Run sunbeam prepare-node-script on the given machine."""
        script_cmd = "sunbeam prepare-node-script"
        if bootstrap:
            script_cmd += " --bootstrap"
        if client:
            script_cmd += " --client"
        with report.step(f"Prepare node {machine.hostname}"):
            result = self._ssh.run(
                machine.ip,
                f"{script_cmd} | bash -x",
                timeout=timeout,
            )
        return result

    def bootstrap(
        self,
        machine: MachineConfig,
        role: str,
        manifest_path: str | None = None,
        *,
        overlay_with_snap_manifest: bool = False,
        snap_manifest_channel: str | None = None,
        timeout: int = 4000,
    ) -> CommandResult:
        """Bootstrap the sunbeam cluster on the primary machine."""
        remote_manifest_path = self._prepare_remote_manifest(
            machine,
            manifest_path,
            overlay_with_snap_manifest=overlay_with_snap_manifest,
            snap_manifest_channel=snap_manifest_channel,
        )
        command = f"sunbeam cluster bootstrap --accept-defaults --role {role}"
        if remote_manifest_path is not None:
            command = f"{command} --manifest {remote_manifest_path}"
        with report.step(f"Bootstrap sunbeam cluster with role {role!r}"):
            result = self._ssh.run(
                machine.ip,
                command,
                timeout=timeout,
            )
            result.check()
        return result

    def configure(
        self, machine: MachineConfig, openrc: str = "demo-openrc", timeout: int = 900
    ) -> CommandResult:
        """Configure the sunbeam deployment."""
        with report.step("Configure sunbeam deployment"):
            result = self._ssh.run(
                machine.ip,
                f"sunbeam configure --accept-defaults --openrc {openrc}",
                timeout=timeout,
            )
            result.check()
        return result

    def resize(self, machine: MachineConfig, timeout: int = 3600) -> CommandResult:
        """Resize the cluster to fit the current set of nodes."""
        with report.step("Resize sunbeam cluster"):
            result = self._ssh.run(
                machine.ip,
                "sunbeam cluster resize",
                timeout=timeout,
            )
            result.check()
        return result

    def generate_join_token(
        self, machine: MachineConfig, fqdn: str, token_path: str, timeout: int = 300
    ) -> str:
        """Generate a join token for the given machine FQDN.

        Writes the token to token_path on the primary machine and returns the
        token string (stripped of surrounding whitespace).
        """
        with report.step(f"Generate join token for {fqdn!r}"):
            result = self._ssh.run(
                machine.ip,
                f"sunbeam cluster add {fqdn} -o {token_path}",
                timeout=timeout,
            )
            result.check()
            token = self._ssh.read_file(machine.ip, token_path)
        return token.strip()

    def join(
        self,
        machine: MachineConfig,
        role: str,
        token: str,
        timeout: int = 3600,
    ) -> CommandResult:
        """Join the cluster from the given machine using the provided token."""
        with report.step(f"Join cluster from {machine.hostname} with role {role!r}"):
            result = self._ssh.run(
                machine.ip,
                f"sunbeam cluster join --role {role} {token}",
                timeout=timeout,
            )
            result.check()
        return result

    def enable(
        self, machine: MachineConfig, feature: str, timeout: int = 600
    ) -> CommandResult:
        """Enable a sunbeam feature."""
        with report.step(f"Enable sunbeam feature {feature!r}"):
            result = self._ssh.run(
                machine.ip,
                f"sunbeam enable {feature}",
                timeout=timeout,
            )
            result.check()
        return result

    def cloud_config(self, machine: MachineConfig, timeout: int = 300) -> CommandResult:
        """Configure the OpenStack client on the primary machine."""
        with report.step("Configure OpenStack client on primary machine"):
            result = self._ssh.run(
                machine.ip,
                "sunbeam cloud-config --update --admin",
                timeout=timeout,
            )
            result.check()
            result = self._ssh.run(
                machine.ip,
                "sunbeam cloud-config --update",
                timeout=timeout,
            )
        return result

    # ── MAAS provisioning ─────────────────────────────────────────────────────

    def add_maas_provider(
        self,
        machine: MachineConfig,
        endpoint: str,
        api_key: str,
        deployment_name: str = "maas",
        timeout: int = 120,
    ) -> CommandResult:
        """Register a MAAS provider with Sunbeam."""
        with report.step(f"Add MAAS provider at {endpoint!r}"):
            return self._ssh.run(
                machine.ip,
                f"sunbeam deployment add maas {deployment_name} {api_key} {endpoint}",
                timeout=timeout,
            ).check()

    def map_maas_network_space(
        self,
        machine: MachineConfig,
        space: str,
        network: str,
        timeout: int = 60,
    ) -> CommandResult:
        """Map a MAAS network space to a Sunbeam network."""
        with report.step(f"Map MAAS space {space!r} to network {network!r}"):
            return self._ssh.run(
                machine.ip,
                f"sunbeam deployment space map {space}:{network}",
                timeout=timeout,
            ).check()

    def bootstrap_juju_controller(
        self,
        machine: MachineConfig,
        controller_name: str | None = None,
        manifest_path: str | None = None,
        *,
        overlay_with_snap_manifest: bool = False,
        snap_manifest_channel: str | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        """Bootstrap the orchestration layer on the MAAS provider."""
        remote_manifest_path = self._prepare_remote_manifest(
            machine,
            manifest_path,
            overlay_with_snap_manifest=overlay_with_snap_manifest,
            snap_manifest_channel=snap_manifest_channel,
        )
        cmd = "sunbeam cluster bootstrap --accept-defaults"
        if controller_name:
            cmd += f" --controller {controller_name}"
        if remote_manifest_path:
            cmd += f" --manifest {remote_manifest_path}"
        with report.step("Bootstrap orchestration layer via MAAS"):
            return self._ssh.run(machine.ip, cmd, timeout=timeout).check()

    def validate_deployment(
        self, machine: MachineConfig, timeout: int = 300
    ) -> CommandResult:
        """Validate the configured deployment substrate."""
        with report.step("Validate deployment"):
            return self._ssh.run(
                machine.ip,
                "sunbeam deployment validate",
                timeout=timeout,
            ).check()

    def deploy_cloud(
        self,
        machine: MachineConfig,
        manifest_path: str | None = None,
        *,
        overlay_with_snap_manifest: bool = False,
        snap_manifest_channel: str | None = None,
        timeout: int = 7200,
    ) -> CommandResult:
        """Deploy OpenStack on the bootstrapped Juju controller."""
        remote_manifest_path = self._prepare_remote_manifest(
            machine,
            manifest_path,
            overlay_with_snap_manifest=overlay_with_snap_manifest,
            snap_manifest_channel=snap_manifest_channel,
        )
        cmd = "sunbeam cluster deploy"
        if remote_manifest_path:
            cmd += f" --manifest {remote_manifest_path}"
        with report.step("Deploy OpenStack cloud"):
            return self._ssh.run(
                machine.ip,
                cmd,
                timeout=timeout,
            ).check()

    # ── External Juju ─────────────────────────────────────────────────────────

    def register_juju_controller(
        self,
        machine: MachineConfig,
        name: str,
        token: str,
        timeout: int = 120,
    ) -> CommandResult:
        """Register an existing Juju controller with Sunbeam."""
        cmd = f"sunbeam juju register-controller {name} {token}"
        with report.step(f"Register external Juju controller {name!r}"):
            return self._ssh.run(
                machine.ip,
                cmd,
                timeout=timeout,
            ).check()

    def set_proxy(
        self,
        machine: MachineConfig,
        http_proxy: str | None = None,
        https_proxy: str | None = None,
        no_proxy: str | None = None,
        timeout: int = 120,
    ) -> CommandResult:
        """Update Sunbeam proxy configuration."""
        cmd = "sunbeam proxy set"
        if http_proxy:
            cmd += f" --http-proxy {http_proxy}"
        if https_proxy:
            cmd += f" --https-proxy {https_proxy}"
        if no_proxy:
            cmd += f" --no-proxy {no_proxy}"
        with report.step("Configure Sunbeam proxy settings"):
            return self._ssh.run(machine.ip, cmd, timeout=timeout).check()

    def bootstrap_with_controller(
        self,
        machine: MachineConfig,
        controller_name: str,
        role: str | None = None,
        manifest_path: str | None = None,
        *,
        overlay_with_snap_manifest: bool = False,
        snap_manifest_channel: str | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        """Bootstrap Sunbeam using an external Juju controller."""
        remote_manifest_path = self._prepare_remote_manifest(
            machine,
            manifest_path,
            overlay_with_snap_manifest=overlay_with_snap_manifest,
            snap_manifest_channel=snap_manifest_channel,
        )
        cmd = "sunbeam cluster bootstrap --accept-defaults"
        if role is not None:
            cmd += f" --role {role}"
        cmd += f" --controller {controller_name}"
        if remote_manifest_path:
            cmd += f" --manifest {remote_manifest_path}"
        with report.step(f"Bootstrap with external controller {controller_name!r}"):
            return self._ssh.run(
                machine.ip,
                cmd,
                timeout=timeout,
            ).check()

    def cluster_status(
        self, machine: MachineConfig, timeout: int = 300, attach_output: bool = True
    ) -> CommandResult:
        """Return current cluster status."""
        with report.step("Get cluster status"):
            return self._ssh.run(
                machine.ip,
                "sunbeam cluster status",
                timeout=timeout,
                attach_output=attach_output,
            )

    def wait_for_ready(
        self,
        machine: MachineConfig,
        timeout: int = 1800,
        poll_interval: int = 15,
    ) -> CommandResult:
        """Wait until cluster status reports a ready state."""
        deadline = time.monotonic() + timeout
        last_status = ""
        with report.step(f"Wait for cluster ready (timeout={timeout}s)"):
            while time.monotonic() < deadline:
                status_result = self.cluster_status(
                    machine, timeout=min(poll_interval, 60), attach_output=False
                )
                last_status = status_result.stdout.strip()
                if status_result.succeeded and "ready" in last_status.lower():
                    report.note("Cluster reported ready")
                    return status_result
                time.sleep(poll_interval)
        raise TimeoutError(
            "Timed out waiting for cluster to become ready. "
            f"Last status output:\n{last_status}"
        )
