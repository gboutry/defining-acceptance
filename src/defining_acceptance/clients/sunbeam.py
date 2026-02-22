"""High-level wrapper around the sunbeam CLI executed via SSH."""

from __future__ import annotations

from pathlib import Path

from defining_acceptance.clients.ssh import CommandResult, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig


class SunbeamClient:
    """Execute sunbeam CLI commands on a remote machine via SSH."""

    _REMOTE_MANIFEST_PATH = "/home/ubuntu/manifest.yaml"

    def __init__(self, ssh: SSHRunner) -> None:
        self._ssh = ssh

    def _prepare_remote_manifest(
        self,
        machine: MachineConfig,
        manifest_path: str | None,
    ) -> str | None:
        """Upload a local manifest file and return its remote path."""
        if manifest_path is None:
            return None

        local_manifest_path = Path(manifest_path).expanduser().resolve(strict=False)
        if not local_manifest_path.is_file():
            raise FileNotFoundError(f"Manifest file not found: {local_manifest_path}")

        with report.step(f"Upload manifest to {machine.hostname}"):
            self._ssh.upload_file(
                machine.ip,
                local_manifest_path,
                self._REMOTE_MANIFEST_PATH,
            )

        return self._REMOTE_MANIFEST_PATH

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
        timeout: int = 600,
    ) -> CommandResult:
        """Run sunbeam prepare-node-script on the given machine."""
        script_cmd = "sunbeam prepare-node-script"
        if bootstrap:
            script_cmd += " --bootstrap"
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
        timeout: int = 3600,
    ) -> CommandResult:
        """Bootstrap the sunbeam cluster on the primary machine."""
        remote_manifest_path = self._prepare_remote_manifest(machine, manifest_path)
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
        timeout: int = 120,
    ) -> CommandResult:
        """Register a MAAS provider with Sunbeam."""
        with report.step(f"Add MAAS provider at {endpoint!r}"):
            return self._ssh.run(
                machine.ip,
                f"sunbeam provider add maas --endpoint {endpoint} --api-key {api_key}",
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
                f"sunbeam provider maas map-space --space {space} --network {network}",
                timeout=timeout,
            ).check()

    def bootstrap_juju_controller(
        self, machine: MachineConfig, timeout: int = 3600
    ) -> CommandResult:
        """Bootstrap the Juju controller on the MAAS provider."""
        with report.step("Bootstrap Juju controller via MAAS"):
            return self._ssh.run(
                machine.ip,
                "sunbeam controller bootstrap",
                timeout=timeout,
            ).check()

    def deploy_cloud(
        self,
        machine: MachineConfig,
        manifest_path: str | None = None,
        timeout: int = 7200,
    ) -> CommandResult:
        """Deploy OpenStack on the bootstrapped Juju controller."""
        remote_manifest_path = self._prepare_remote_manifest(machine, manifest_path)
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
        endpoint: str,
        user: str,
        password: str,
        name: str | None = None,
        timeout: int = 120,
    ) -> CommandResult:
        """Register an existing Juju controller with Sunbeam."""
        cmd = (
            f"sunbeam controller register"
            f" --endpoint {endpoint}"
            f" --user {user}"
            f" --password {password}"
        )
        if name:
            cmd += f" --name {name}"
        with report.step(f"Register external Juju controller at {endpoint!r}"):
            return self._ssh.run(
                machine.ip,
                cmd,
                timeout=timeout,
            ).check()

    def bootstrap_with_controller(
        self,
        machine: MachineConfig,
        controller_name: str,
        role: str,
        manifest_path: str | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        """Bootstrap Sunbeam using an external Juju controller."""
        remote_manifest_path = self._prepare_remote_manifest(machine, manifest_path)
        cmd = (
            f"sunbeam cluster bootstrap --accept-defaults"
            f" --role {role}"
            f" --controller {controller_name}"
        )
        if remote_manifest_path:
            cmd += f" --manifest {remote_manifest_path}"
        with report.step(f"Bootstrap with external controller {controller_name!r}"):
            return self._ssh.run(
                machine.ip,
                cmd,
                timeout=timeout,
            ).check()
