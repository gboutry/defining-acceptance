"""Step definitions for different-host internal network throughput tests."""

import json
import os
from contextlib import suppress

from defining_acceptance.clients.openstack import OpenStackClient
from defining_acceptance.clients.ssh import SSHRunner
from defining_acceptance.testbed import TestbedConfig
from defining_acceptance.utils import CleanupStack
import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.reporting import report
from tests._vm_helpers import create_vm, vm_ssh

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

_MIN_THROUGHPUT_GBPS = 1.0

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario(
    "performance/network_throughput.feature",
    "Internal network throughput on different host",
)
def test_internal_network_different_host():
    pass


# ── Steps ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def client_vm() -> dict:
    return {}


@pytest.fixture
def throughput_result() -> dict:
    return {}


@given("a second VM on the same network but different host")
def setup_vms_different_host(
    demo_os_runner: OpenStackClient,
    testbed: TestbedConfig,
    ssh_runner: SSHRunner,
    running_vm: dict,
    client_vm: dict,
    cleanup_stack: CleanupStack,
):
    """Create a client VM with anti-affinity to the server VM.

    On a single-node deployment there is only one hypervisor, so anti-affinity
    cannot be satisfied; the test is skipped in that case.
    """
    if MOCK_MODE:
        client_vm.update(
            {
                "server_id": "mock-client",
                "key_path": "/tmp/mock.pem",
                "primary_ip": "192.168.1.100",
                "floating_ip": "192.0.2.2",
                "internal_ip": "10.0.0.6",
            }
        )
        return

    if testbed.is_single_node:
        pytest.skip(
            "Single-node deployment — cannot place VMs on different hypervisors"
        )

    with report.step("Creating anti-affinity server group"):
        sg = demo_os_runner.server_group_create(
            f"anti-affinity-{running_vm['server_name']}", "anti-affinity"
        )
        sg_id = sg["id"]
        cleanup_stack.add(demo_os_runner.server_group_delete, sg_id)

    resources = create_vm(
        demo_os_runner,
        testbed,
        ssh_runner,
        cleanup_stack,
        network_name=running_vm.get("network_name"),
        server_group_id=sg_id,
    )
    client_vm.update(resources)

    with report.step("Installing iperf3 on client VM"):
        vm_ssh(
            ssh_runner,
            resources["primary_ip"],
            resources["floating_ip"],
            resources["key_path"],
            "sudo apt-get install -y iperf3 -qq 2>/dev/null || true",
            timeout=120,
        )
    report.note(
        f"Client VM {resources['server_name']} placed on a different host "
        f"(anti-affinity)"
    )


@pytest.fixture
@when("I measure throughput between the VMs")
def measure_throughput(running_vm, client_vm, ssh_runner, throughput_result):
    """Run iperf3 client → server across different hypervisors and record Gbps."""
    if MOCK_MODE:
        throughput_result["gbps"] = 1.8
        return

    server_internal_ip = running_vm["internal_ip"]
    client_floating_ip = client_vm["floating_ip"]
    client_key_path = client_vm["key_path"]
    primary_ip = client_vm["primary_ip"]

    with report.step(
        f"Running iperf3 (different-host) to server ({server_internal_ip})"
    ):
        result = vm_ssh(
            ssh_runner,
            primary_ip,
            client_floating_ip,
            client_key_path,
            f"iperf3 -c {server_internal_ip} -t 10 -J 2>/dev/null",
            timeout=60,
        )

    assert result.succeeded, (
        f"iperf3 client failed (rc={result.returncode}):\n{result.stderr}"
    )
    try:
        data = json.loads(result.stdout)
        bits_per_sec = data["end"]["sum_received"]["bits_per_second"]
        gbps = bits_per_sec / 1e9
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"Failed to parse iperf3 JSON output: {exc}\n{result.stdout}"
        ) from exc

    throughput_result["gbps"] = gbps
    report.note(f"Cross-host throughput: {gbps:.2f} Gbps")


@then("throughput should be at least 1 Gbps")
def check_throughput_1gbps(throughput_result):
    """Assert the measured throughput meets the minimum threshold."""
    if MOCK_MODE:
        return
    gbps = throughput_result["gbps"]
    assert gbps >= _MIN_THROUGHPUT_GBPS, (
        f"Cross-host throughput {gbps:.2f} Gbps is below "
        f"the {_MIN_THROUGHPUT_GBPS} Gbps threshold"
    )
    report.note(
        f"Cross-host throughput {gbps:.2f} Gbps ≥ {_MIN_THROUGHPUT_GBPS} Gbps ✓"
    )
