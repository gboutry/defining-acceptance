from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.clients.sunbeam import SunbeamClient
from defining_acceptance.testbed import MachineConfig


class _FakeSSH:
    def __init__(self, *, base_manifest: str = "") -> None:
        self._base_manifest = base_manifest
        self.upload_calls: list[tuple[str, Path, str]] = []
        self.write_calls: list[tuple[str, str, str]] = []
        self.run_calls: list[tuple[str, str]] = []

    def upload_file(self, hostname: str, local_path: Path, remote_path: str) -> None:
        self.upload_calls.append((hostname, local_path, remote_path))

    def write_file(self, hostname: str, remote_path: str, content: str) -> None:
        self.write_calls.append((hostname, remote_path, content))

    def run(self, hostname: str, command: str, timeout: int = 30) -> CommandResult:
        del timeout
        self.run_calls.append((hostname, command))
        return CommandResult(
            command=command,
            returncode=0,
            stdout=self._base_manifest,
            stderr="",
        )


def _machine() -> MachineConfig:
    return MachineConfig(hostname="sunbeam", ip="10.0.0.10", roles=[])


def test_prepare_remote_manifest_uploads_plain_file(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("foo: bar\n", encoding="utf-8")
    ssh = _FakeSSH()
    client = SunbeamClient(ssh=ssh)  # type: ignore[arg-type]

    remote_path = client._prepare_remote_manifest(_machine(), str(overlay))

    assert remote_path == "/home/ubuntu/manifest.yaml"
    assert len(ssh.upload_calls) == 1
    assert not ssh.run_calls
    assert not ssh.write_calls


def test_prepare_remote_manifest_overlays_snap_manifest(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        "features:\n  dashboard: true\nconfig:\n  retries: 5\n", encoding="utf-8"
    )
    base_manifest = (
        "features:\n  dashboard: false\n  logging: true\nconfig:\n  timeout: 10\n"
    )
    ssh = _FakeSSH(base_manifest=base_manifest)
    client = SunbeamClient(ssh=ssh)  # type: ignore[arg-type]

    remote_path = client._prepare_remote_manifest(
        _machine(),
        str(overlay),
        overlay_with_snap_manifest=True,
        snap_manifest_channel="2024.1/edge",
    )

    assert remote_path == "/home/ubuntu/manifest.yaml"
    assert ssh.run_calls == [
        (
            "10.0.0.10",
            "sudo cat '/snap/openstack/current/etc/manifests/2024.1/edge.yml'",
        )
    ]
    assert len(ssh.write_calls) == 1
    merged = yaml.safe_load(ssh.write_calls[0][2])
    assert merged == {
        "features": {"dashboard": True, "logging": True},
        "config": {"timeout": 10, "retries": 5},
    }


def test_prepare_remote_manifest_overlay_requires_channel(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("foo: bar\n", encoding="utf-8")
    ssh = _FakeSSH()
    client = SunbeamClient(ssh=ssh)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="deployment.channel"):
        client._prepare_remote_manifest(
            _machine(),
            str(overlay),
            overlay_with_snap_manifest=True,
        )


def test_map_maas_network_space_uses_space_network_syntax() -> None:
    ssh = _FakeSSH()
    client = SunbeamClient(ssh=ssh)  # type: ignore[arg-type]

    result = client.map_maas_network_space(_machine(), space="public", network="public")

    assert result.succeeded
    assert ssh.run_calls[-1] == (
        "10.0.0.10",
        "sunbeam deployment space map public:public",
    )
