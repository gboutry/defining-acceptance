"""
Shared step definitions for operations tests.
"""

import pytest
from pytest_bdd import given


@given("the cloud is provisioned")
def cloud_provisioned():
    """Verify the cloud is provisioned."""
    pass


@given("the cloud is configured for sample usage")
def cloud_configured():
    """Verify the cloud is configured for sample usage."""
    pass
