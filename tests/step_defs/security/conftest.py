"""
Shared step definitions for security tests.
"""

import pytest
from pytest_bdd import given


@given("the cloud is provisioned")
def cloud_provisioned():
    pass


@given("the cloud is configured for sample usage")
def cloud_configured():
    pass


@given("a VM is running")
def setup_vm():
    pass
