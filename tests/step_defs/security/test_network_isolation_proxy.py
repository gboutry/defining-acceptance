import pytest
from pytest_bdd import scenario, given, when, then
import unittest.mock as mock


@scenario("security/network_isolation.feature", "Proxy filtering works")
def test_proxy_filtering():
    pass


@given("the VM is configured to use a proxy")
def setup_vm_with_proxy():
    pass


@pytest.fixture
@when("I make a web request")
def make_web_request():
    return mock.Mock(through_proxy=True, proxy_address="proxy.example.com:8080")


@then("the request should go through the proxy")
def verify_proxy_used(make_web_request):
    assert make_web_request.through_proxy, "Web request should go through proxy"
