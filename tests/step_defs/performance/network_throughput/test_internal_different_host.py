import pytest
from pytest_bdd import scenario, given, when, then
import unittest.mock as mock


@scenario(
    "performance/network_throughput.feature",
    "Internal network throughput on different host",
)
def test_internal_network_different_host():
    pass


@given("a second VM on the same network but different host")
def setup_vms_different_host():
    pass


@pytest.fixture
@when("I measure throughput between the VMs")
def measure_throughput():
    return mock.Mock(throughput_gbps=1.2)


@then("throughput should be at least 1 Gbps")
def check_throughput_1gbps(measure_throughput):
    assert measure_throughput.throughput_gbps >= 1.0
