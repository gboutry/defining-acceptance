"""
Provision cloud module for defining acceptance tests.

This module handles reading infrastructure configuration from the sunbeam-proxified-dev
terraform output and providing it to the test framework.
"""

from pathlib import Path
from typing import Any

import yaml


def get_project_root() -> Path:
    """Get the project root directory."""
    # This file is at src/defining_acceptance/provision_cloud/__init__.py
    # So we need to go up 3 levels to get to defining-acceptance/
    return Path(__file__).parent.parent.parent.parent


def get_sunbeam_dev_path() -> Path:
    """Get the path to the sunbeam-proxified-dev terraform directory."""
    return get_project_root().parent / "sunbeam-proxified-dev"


def get_infrastructure_path() -> Path:
    """Get the path to the standardized infrastructure YAML (without IP)."""
    return get_sunbeam_dev_path() / "testbed.yaml"


def get_testbed_with_ip_path() -> Path:
    """Get the path to the testbed YAML with IP (for testbed use)."""
    return get_sunbeam_dev_path() / "testbed_with_ip.yaml"


def load_infrastructure(include_ip: bool = False) -> dict[str, Any]:
    """
    Load the infrastructure configuration from the terraform output.
    
    Args:
        include_ip: If True, load the testbed_with_ip.yaml which includes IP addresses.
                   If False, load the standardized testbed.yaml without IP.
    
    Returns:
        Dictionary containing the infrastructure configuration.
    """
    if include_ip:
        infra_path = get_testbed_with_ip_path()
    else:
        infra_path = get_infrastructure_path()
    
    if not infra_path.exists():
        raise FileNotFoundError(
            f"Infrastructure file not found at {infra_path}. "
            "Please run 'terraform apply' in sunbeam-proxified-dev first."
        )
    
    with open(infra_path, "r") as f:
        return yaml.safe_load(f)


def get_machines(include_ip: bool = False) -> list[dict[str, Any]]:
    """Get the list of machines from the infrastructure configuration."""
    infra = load_infrastructure(include_ip=include_ip)
    return infra.get("machines", [])


def get_machine(hostname: str, include_ip: bool = False) -> dict[str, Any] | None:
    """Get a specific machine by hostname."""
    machines = get_machines(include_ip=include_ip)
    for machine in machines:
        if machine.get("hostname") == hostname:
            return machine
    return None


def get_ssh_private_key_path() -> Path:
    """Get the path to the SSH private key."""
    return get_sunbeam_dev_path() / "ssh_private_key"


def get_ssh_public_key_path() -> Path:
    """Get the path to the SSH public key."""
    return get_sunbeam_dev_path() / "ssh_public_key.pub"


def get_ssh_config() -> dict[str, Any]:
    """Get SSH configuration for connecting to the infrastructure."""
    priv_key_path = get_ssh_private_key_path()
    pub_key_path = get_ssh_public_key_path()
    
    if not priv_key_path.exists():
        raise FileNotFoundError(
            f"SSH private key not found at {priv_key_path}. "
            "Please run 'terraform apply' in sunbeam-proxified-dev first."
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


def get_ssh_key_dir() -> Path:
    """Get the SSH keys directory path."""
    return get_sunbeam_dev_path()
