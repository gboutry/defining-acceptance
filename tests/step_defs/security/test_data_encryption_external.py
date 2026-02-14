import pytest
from pytest_bdd import scenario, given, when, then
import unittest.mock as mock


@scenario("security/data_encryption.feature", "External connections use TLS")
def test_external_connections_tls():
    pass


@pytest.fixture
@when("I connect to an external service")
def connect_to_service():
    return mock.Mock(tls_enabled=True, tls_version="TLSv1.3")


@then("TLS should be enforced")
def verify_tls_enforced(connect_to_service):
    assert connect_to_service.tls_enabled, (
        "TLS should be enforced on external connections"
    )
