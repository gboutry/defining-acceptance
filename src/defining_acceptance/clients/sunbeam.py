"""High-level wrapper around the sunbeam CLI executed via SSH."""

from __future__ import annotations

import time

from defining_acceptance.clients.ssh import CommandResult, SSHRunner
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig


class SunbeamClient:
    """Execute sunbeam CLI commands on a remote machine via SSH."""

    def __init__(self, ssh: SSHRunner, primary: MachineConfig) -> None:
        self._ssh = ssh
        self._primary = primary

    def install_snap(self, channel: str, timeout: int = 600) -> CommandResult:
        """Install the openstack snap on the primary machine.

        Does not call .check() because the snap may already be installed,
        in which case snap returns a non-zero exit code with "already installed"
        in stdout.
        """
        with report.step(f"Install openstack snap from channel {channel!r}"):
            result = self._ssh.run(
                self._primary.ip,
                f"sudo snap install openstack --channel {channel}",
                timeout=timeout,
            )
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
        role: str,
        manifest_path: str | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        """Bootstrap the sunbeam cluster on the primary machine."""
        command = f"sunbeam cluster bootstrap --accept-defaults --role {role}"
        if manifest_path is not None:
            command = f"{command} --manifest {manifest_path}"
        with report.step(f"Bootstrap sunbeam cluster with role {role!r}"):
            result = self._ssh.run(
                self._primary.ip,
                command,
                timeout=timeout,
            )
            result.check()
        return result

    def configure(
        self, openrc: str = "demo-openrc", timeout: int = 300
    ) -> CommandResult:
        """Configure the sunbeam deployment."""
        with report.step("Configure sunbeam deployment"):
            result = self._ssh.run(
                self._primary.ip,
                f"sunbeam configure --accept-defaults --openrc {openrc}",
                timeout=timeout,
            )
            result.check()
        return result

    def generate_join_token(
        self, fqdn: str, token_path: str, timeout: int = 300
    ) -> str:
        """Generate a join token for the given machine FQDN.

        Writes the token to token_path on the primary machine and returns the
        token string (stripped of surrounding whitespace).
        """
        with report.step(f"Generate join token for {fqdn!r}"):
            result = self._ssh.run(
                self._primary.ip,
                f"sunbeam cluster add {fqdn} -o {token_path}",
                timeout=timeout,
            )
            result.check()
            token = self._ssh.read_file(self._primary.ip, token_path)
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

    def enable(self, feature: str, timeout: int = 600) -> CommandResult:
        """Enable a sunbeam feature."""
        with report.step(f"Enable sunbeam feature {feature!r}"):
            result = self._ssh.run(
                self._primary.ip,
                f"sunbeam enable {feature}",
                timeout=timeout,
            )
            result.check()
        return result

    def cluster_status(self, timeout: int = 60) -> CommandResult:
        """Return the current cluster status without raising on failure."""
        with report.step("Get cluster status"):
            result = self._ssh.run(
                self._primary.ip,
                "sunbeam cluster status",
                timeout=timeout,
            )
        return result

    # ── MAAS provisioning ─────────────────────────────────────────────────────

    def add_maas_provider(
        self,
        endpoint: str,
        api_key: str,
        timeout: int = 120,
    ) -> CommandResult:
        """Register a MAAS provider with Sunbeam."""
        with report.step(f"Add MAAS provider at {endpoint!r}"):
            return self._ssh.run(
                self._primary.ip,
                f"sunbeam provider add maas --endpoint {endpoint} --api-key {api_key}",
                timeout=timeout,
            ).check()

    def map_maas_network_space(
        self,
        space: str,
        network: str,
        timeout: int = 60,
    ) -> CommandResult:
        """Map a MAAS network space to a Sunbeam network."""
        with report.step(f"Map MAAS space {space!r} to network {network!r}"):
            return self._ssh.run(
                self._primary.ip,
                f"sunbeam provider maas map-space --space {space} --network {network}",
                timeout=timeout,
            ).check()

    def bootstrap_juju_controller(self, timeout: int = 3600) -> CommandResult:
        """Bootstrap the Juju controller on the MAAS provider."""
        with report.step("Bootstrap Juju controller via MAAS"):
            return self._ssh.run(
                self._primary.ip,
                "sunbeam controller bootstrap",
                timeout=timeout,
            ).check()

    def deploy_cloud(
        self,
        manifest_path: str | None = None,
        timeout: int = 7200,
    ) -> CommandResult:
        """Deploy OpenStack on the bootstrapped Juju controller."""
        cmd = "sunbeam cluster deploy"
        if manifest_path:
            cmd += f" --manifest {manifest_path}"
        with report.step("Deploy OpenStack cloud"):
            return self._ssh.run(
                self._primary.ip,
                cmd,
                timeout=timeout,
            ).check()

    # ── External Juju ─────────────────────────────────────────────────────────

    def register_juju_controller(
        self,
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
                self._primary.ip,
                cmd,
                timeout=timeout,
            ).check()

    def bootstrap_with_controller(
        self,
        controller_name: str,
        role: str,
        manifest_path: str | None = None,
        timeout: int = 3600,
    ) -> CommandResult:
        """Bootstrap Sunbeam using an external Juju controller."""
        cmd = (
            f"sunbeam cluster bootstrap --accept-defaults"
            f" --role {role}"
            f" --controller {controller_name}"
        )
        if manifest_path:
            cmd += f" --manifest {manifest_path}"
        with report.step(f"Bootstrap with external controller {controller_name!r}"):
            return self._ssh.run(
                self._primary.ip,
                cmd,
                timeout=timeout,
            ).check()

    def wait_for_ready(self, timeout: int = 600) -> None:
        """Poll cluster status until it reports ready or the timeout is reached.

        Raises:
            TimeoutError: If the cluster does not become ready within timeout seconds.
        """
        poll_interval = 15
        deadline = time.monotonic() + timeout
        with report.step(f"Wait for cluster to be ready (timeout={timeout}s)"):
            while True:
                result = self.cluster_status()
                if "ready" in result.stdout.lower():
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Cluster did not become ready within {timeout} seconds. "
                        f"Last status output: {result.stdout!r}"
                    )
                time.sleep(min(poll_interval, remaining))
