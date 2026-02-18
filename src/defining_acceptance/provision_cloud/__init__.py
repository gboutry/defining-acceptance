"""
Helpers for loading external infrastructure inputs for acceptance tests.

The defining-acceptance project expects testbed and SSH credentials to be
provided as inputs by the caller.
"""

from pathlib import Path
from typing import Any

import yaml


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent.parent


def get_default_testbed_path() -> Path:
    """Get the default path to the testbed YAML file."""
    return Path.cwd() / "testbed.yaml"


def load_infrastructure(testbed_path: Path | None = None) -> dict[str, Any]:
    """
    Load the infrastructure configuration from the provided testbed YAML file.

    Args:
        testbed_path: Optional path to the testbed YAML.

    Returns:
        Dictionary containing infrastructure configuration.
    """
    infra_path = testbed_path or get_default_testbed_path()

    if not infra_path.exists():
        raise FileNotFoundError(
            f"Infrastructure file not found at {infra_path}. "
            "Provide a testbed file path as input."
        )

    with open(infra_path, "r") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Infrastructure file {infra_path} must contain a mapping")

    return data


def get_machines(testbed_path: Path | None = None) -> list[dict[str, Any]]:
    """Get the list of machines from the infrastructure configuration."""
    infra = load_infrastructure(testbed_path)
    machines = infra.get("machines", [])
    return machines if isinstance(machines, list) else []


def get_machine(
    hostname: str, testbed_path: Path | None = None
) -> dict[str, Any] | None:
    """Get a specific machine by hostname."""
    machines = get_machines(testbed_path)
    for machine in machines:
        if isinstance(machine, dict) and machine.get("hostname") == hostname:
            return machine
    return None


def get_default_ssh_private_key_path() -> Path:
    """Get the default path to the SSH private key."""
    return Path.cwd() / "ssh_private_key"


def get_default_ssh_public_key_path() -> Path:
    """Get the default path to the SSH public key."""
    return Path.cwd() / "ssh_public_key.pub"


def get_ssh_config(
    private_key_path: Path | None = None,
    public_key_path: Path | None = None,
) -> dict[str, Any]:
    """Get SSH configuration for connecting to the provided infrastructure."""
    priv_key_path = private_key_path or get_default_ssh_private_key_path()
    pub_key_path = public_key_path or get_default_ssh_public_key_path()

    if not priv_key_path.exists():
        raise FileNotFoundError(
            f"SSH private key not found at {priv_key_path}. "
            "Provide an SSH private key path as input."
        )

    with open(priv_key_path, "r") as f:
        private_key = f.read()

    public_key = ""
    if pub_key_path.exists():
        with open(pub_key_path, "r") as f:
            public_key = f.read().strip()

    return {
        "private_key": private_key,
        "public_key": public_key,
        "key_path": str(priv_key_path),
    }
