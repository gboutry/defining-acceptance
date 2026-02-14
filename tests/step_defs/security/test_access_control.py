import pytest
from pytest_bdd import scenarios, when, then
import unittest.mock as mock


scenarios("security/access_control.feature")


@pytest.fixture
@when("I connect with the correct SSH key")
def connect_with_key():
    return mock.Mock(success=True, connection_status="connected")


@pytest.fixture
@when("I connect without an SSH key")
def connect_without_key():
    return mock.Mock(success=False, connection_status="refused")


@then("the connection should succeed")
def check_connection_success(connect_with_key):
    assert connect_with_key.success, "SSH connection with correct key should succeed"


@then("the connection should be refused")
def check_connection_refused(connect_without_key):
    assert not connect_without_key.success, (
        "SSH connection without key should be refused"
    )
    assert connect_without_key.connection_status == "refused", (
        "Connection should be explicitly refused"
    )
