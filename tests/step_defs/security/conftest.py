"""Shared step definitions for security tests."""

import os

from defining_acceptance.clients.openstack import OpenStackClient
from defining_acceptance.clients.ssh import SSHRunner
from defining_acceptance.testbed import TestbedConfig
from defining_acceptance.utils import DeferStack
import pytest
from pytest_bdd import given

from defining_acceptance.reporting import report
from tests._vm_helpers import create_vm

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# "the cloud is provisioned" and "the cloud is configured for sample usage"
# are defined in tests/conftest.py and apply here.


@pytest.fixture
def running_vm() -> dict:
    """Mutable container populated by 'a VM is running'."""
    return {}


@pytest.fixture
def second_vm() -> dict:
    """Mutable container populated by steps that create an additional VM."""
    return {}


@given("a VM is running")
def setup_running_vm(
    demo_os_runner: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    running_vm: dict,
    defer: DeferStack,
):
    """Create a VM with a floating IP and wait for SSH to become available."""
    if MOCK_MODE:
        running_vm.update(
            {
                "server_id": "mock-server",
                "server_name": "mock-vm",
                "keypair_name": "mock-key",
                "key_path": "/tmp/mock.pem",
                "primary_ip": "192.168.1.100",
                "floating_ip": "192.0.2.1",
                "internal_ip": "10.0.0.5",
                "network_name": "default",
            }
        )
        return
    resources = create_vm(demo_os_runner, testbed, ssh_runner, defer)
    running_vm.update(resources)
    report.note(f"VM {resources['server_name']} running at {resources['floating_ip']}")
