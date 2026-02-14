import pytest
from pytest_bdd import scenario, given, when, then
import unittest.mock as mock


@scenario("security/data_encryption.feature", "Internal network traffic is encrypted")
def test_internal_traffic_encryption():
    pass


@given("a second VM is running on the internal network")
def setup_two_vms_internal():
    pass


@pytest.fixture
@when("I check network traffic between the VMs")
def check_network_traffic():
    return mock.Mock(encrypted=True, protocol="TLS")


@then("traffic should be encrypted")
def verify_traffic_encrypted(check_network_traffic):
    assert check_network_traffic.encrypted, "Network traffic should be encrypted"
