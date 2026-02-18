"""SSH command runner for executing commands on remote machines."""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import paramiko

from defining_acceptance.reporting import report


@dataclass
class CommandResult:
    """Result of a remote command execution."""

    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def check(self) -> CommandResult:
        """Raise CommandError if the command exited with a non-zero return code."""
        if self.returncode != 0:
            raise CommandError(self)
        return self


class CommandError(Exception):
    """Raised when a remote command exits with a non-zero return code."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"Command failed (rc={result.returncode}): {result.command}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


class SSHRunner:
    """Executes commands and transfers files on remote machines via SSH.

    A new SSH connection is opened for each operation and closed immediately
    after. This avoids stale-connection problems during long-running test
    sessions while keeping the implementation simple.

    Example::

        runner = SSHRunner(user="ubuntu", private_key_path="./ssh_private_key")
        result = runner.run("10.0.0.10", ["sunbeam", "cluster", "status"])
        result.check()   # raises CommandError on non-zero exit
    """

    def __init__(self, user: str, private_key_path: str | Path) -> None:
        self._user = user
        self._private_key_path = str(private_key_path)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _connect(self, hostname: str) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=hostname,
            username=self._user,
            key_filename=self._private_key_path,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )
        return client

    # ── Command execution ─────────────────────────────────────────────────────

    def run(
        self,
        hostname: str,
        command: str | Sequence[str],
        timeout: int = 600,
        *,
        attach_output: bool = True,
    ) -> CommandResult:
        """Run a command on a remote host.

        Args:
            hostname: IP address or resolvable hostname of the target machine.
            command: Shell string or list of arguments. Lists are joined with
                ``shlex.quote`` so they are safe to pass through the shell.
            timeout: Maximum seconds to wait for the command to complete before
                raising ``subprocess.TimeoutExpired``.
            attach_output: When *True* (default), non-empty stdout and stderr
                are attached to the current Allure report step as text
                attachments.

        Returns:
            A :class:`CommandResult` with the exit code, stdout, and stderr.

        Raises:
            subprocess.TimeoutExpired: If the command exceeds *timeout*.
        """
        if isinstance(command, (list, tuple)):
            command_str = " ".join(shlex.quote(str(part)) for part in command)
        else:
            command_str = command

        client = self._connect(hostname)
        try:
            _, stdout_chan, stderr_chan = client.exec_command(command_str)
            channel = stdout_chan.channel
            deadline = time.monotonic() + timeout

            while not channel.exit_status_ready():
                if time.monotonic() > deadline:
                    channel.close()
                    raise subprocess.TimeoutExpired(command_str, timeout)
                time.sleep(0.2)

            returncode = channel.recv_exit_status()
            stdout_text = stdout_chan.read().decode("utf-8", errors="replace")
            stderr_text = stderr_chan.read().decode("utf-8", errors="replace")
        finally:
            client.close()

        result = CommandResult(
            command=command_str,
            returncode=returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )

        if attach_output:
            label = command_str[:80]
            if stdout_text.strip():
                report.attach_text(stdout_text, f"stdout: {label}")
            if stderr_text.strip():
                report.attach_text(stderr_text, f"stderr: {label}")

        return result

    # ── File transfer ─────────────────────────────────────────────────────────

    def read_file(self, hostname: str, remote_path: str) -> str:
        """Read a text file from a remote host via SFTP.

        Returns:
            The file contents decoded as UTF-8.
        """
        client = self._connect(hostname)
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_path, "r") as fh:
                    return fh.read().decode("utf-8", errors="replace")
            finally:
                sftp.close()
        finally:
            client.close()

    def write_file(self, hostname: str, remote_path: str, content: str) -> None:
        """Write a text file to a remote host via SFTP.

        The file is created or overwritten. Parent directories must exist.
        """
        client = self._connect(hostname)
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_path, "w") as fh:
                    fh.write(content.encode("utf-8"))
            finally:
                sftp.close()
        finally:
            client.close()

    def upload_file(
        self,
        hostname: str,
        local_path: str | Path,
        remote_path: str,
    ) -> None:
        """Upload a local file to a remote host via SFTP.

        The remote parent directory must exist.
        """
        client = self._connect(hostname)
        try:
            sftp = client.open_sftp()
            try:
                sftp.put(str(local_path), remote_path)
            finally:
                sftp.close()
        finally:
            client.close()
