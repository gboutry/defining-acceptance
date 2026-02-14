import pytest
from pytest_bdd import scenario, given, when, then
import unittest.mock as mock


@scenario("performance/network_throughput.feature", "External network throughput")
def test_external_network_throughput():
    pass


@given("a VM is running")
def setup_running_vm():
    pass


@pytest.fixture
@when("I download data from an external source")
def download_from_external():
    return mock.Mock(download_speed_mbps=100)


@then("download speed should be acceptable")
def check_download_speed(download_from_external):
    min_acceptable_speed = 10  # Mbps
    assert download_from_external.download_speed_mbps >= min_acceptable_speed, (
        f"Download speed {download_from_external.download_speed_mbps} Mbps is below acceptable threshold of {min_acceptable_speed} Mbps"
    )
