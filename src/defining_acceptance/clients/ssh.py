"""SSH command runner for executing commands on remote machines."""

from __future__ import annotations

import re
import select
import shlex
import subprocess
import time
import uuid
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


_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9._-]")


class SSHRunner:
    """Executes commands and transfers files on remote machines via SSH.

    A new SSH connection is opened for each operation and closed immediately
    after.  stdout and stderr are streamed incrementally via ``select`` as
    data arrives, so that long-running commands with large output never stall
    waiting for the channel buffer to drain.

    When *tmp_dir* is supplied, each command's output is also written to a
    pair of persistent log files inside that directory::

        <host>__<cmd_prefix>__<uid>__stdout.log
        <host>__<cmd_prefix>__<uid>__stderr.log

    The files survive the command and are useful for post-mortem analysis.
    The caller is responsible for cleaning up *tmp_dir*; set ``KEEP_TMP=1``
    in the environment as a signal to skip deletion.

    Example::

        runner = SSHRunner(user="ubuntu", private_key_path="./ssh_private_key")
        result = runner.run("10.0.0.10", ["sunbeam", "cluster", "status"])
        result.check()   # raises CommandError on non-zero exit
    """

    def __init__(
        self,
        user: str,
        private_key_path: str | Path,
        tmp_dir: Path | None = None,
    ) -> None:
        self._user = user
        self._private_key_path = str(private_key_path)
        self._tmp_dir = tmp_dir

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

        stdout and stderr are streamed incrementally using ``select`` so that
        the SSH channel buffer never fills up regardless of how much output
        the remote process produces.

        Args:
            hostname: IP address or resolvable hostname of the target machine.
            command: Shell string or list of arguments.  Lists are joined with
                ``shlex.quote`` so they are safe to pass through the shell.
            timeout: Maximum seconds to wait for the command to complete.
            attach_output: When *True* (default) and the command produces
                non-empty output, attach it to the current Allure step (or
                log it when Allure is not available).

        Returns:
            A :class:`CommandResult` with the exit code, stdout, and stderr.

        Raises:
            subprocess.TimeoutExpired: If the command exceeds *timeout*.
        """
        if isinstance(command, (list, tuple)):
            command_str = " ".join(shlex.quote(str(part)) for part in command)
        else:
            command_str = command

        # Optionally open persistent log files for this invocation.
        stdout_path: Path | None = None
        stderr_path: Path | None = None
        stdout_file = None
        stderr_file = None

        if self._tmp_dir is not None:
            uid = uuid.uuid4().hex[:8]
            safe_host = _SAFE_CHARS.sub("_", hostname)
            safe_cmd = _SAFE_CHARS.sub("_", command_str[:40]).strip("_")
            stdout_path = self._tmp_dir / f"{safe_host}__{safe_cmd}__{uid}__stdout.log"
            stderr_path = self._tmp_dir / f"{safe_host}__{safe_cmd}__{uid}__stderr.log"
            stdout_file = stdout_path.open("w", encoding="utf-8", errors="replace")
            stderr_file = stderr_path.open("w", encoding="utf-8", errors="replace")

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        client = self._connect(hostname)
        try:
            _, stdout_chan, stderr_chan = client.exec_command(command_str)
            channel = stdout_chan.channel
            deadline = time.monotonic() + timeout

            while not channel.exit_status_ready():
                if time.monotonic() > deadline:
                    channel.close()
                    raise subprocess.TimeoutExpired(command_str, timeout)

                # Block up to 100 ms waiting for data; avoids a busy-loop.
                rl, _, _ = select.select([channel], [], [], 0.1)
                if rl:
                    if channel.recv_ready():
                        data = channel.recv(4096).decode("utf-8", errors="replace")
                        stdout_chunks.append(data)
                        if stdout_file:
                            stdout_file.write(data)
                            stdout_file.flush()
                    if channel.recv_stderr_ready():
                        data = channel.recv_stderr(4096).decode(
                            "utf-8", errors="replace"
                        )
                        stderr_chunks.append(data)
                        if stderr_file:
                            stderr_file.write(data)
                            stderr_file.flush()

            # Drain any data that arrived between the last select and exit.
            while channel.recv_ready():
                data = channel.recv(4096).decode("utf-8", errors="replace")
                stdout_chunks.append(data)
                if stdout_file:
                    stdout_file.write(data)
            while channel.recv_stderr_ready():
                data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                stderr_chunks.append(data)
                if stderr_file:
                    stderr_file.write(data)

            returncode = channel.recv_exit_status()
        finally:
            client.close()
            if stdout_file:
                stdout_file.close()
            if stderr_file:
                stderr_file.close()

        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)

        result = CommandResult(
            command=command_str,
            returncode=returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )

        if attach_output:
            label = command_str[:80]
            if stdout_text.strip():
                if stdout_path is not None:
                    report.attach_file(stdout_path, f"stdout: {label}")
                else:
                    report.attach_text(stdout_text, f"stdout: {label}")
            if stderr_text.strip():
                if stderr_path is not None:
                    report.attach_file(stderr_path, f"stderr: {label}")
                else:
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
