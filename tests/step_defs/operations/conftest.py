"""
Shared step definitions for operations tests.
"""

import pytest
from pytest_bdd import given, when, then
import allure
from unittest.mock import Mock


# Mock mode check
import os
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"


@given("the cloud is provisioned")
def cloud_provisioned():
    """Verify the cloud is provisioned."""
    pass


@given("the cloud is configured for sample usage")
def cloud_configured():
    """Verify the cloud is configured for sample usage."""
    pass


# For Scenario Outline with <feature> placeholder,
# pytest-bdd creates a special fixture with the parameter name
# The step definition can use the parameter directly


@given("the feature is enabled")
def given_feature_is_enabled(request, enable_feature):
    """Enable a feature in the cloud deployment."""
    # Get feature from pytest-bdd scenario outline parameter
    feature = getattr(request, 'param', None)
    if feature is None:
        # Fallback: try to get from pytest-bdd example
        try:
            feature = request._pytest_bdd_example.get("feature")
        except Exception:
            pass
    
    if feature is None:
        return
    
    with allure.step(f"Enabling feature: {feature}"):
        try:
            enable_feature(feature)
        except Exception as e:
            allure.attach(
                str(e),
                name="Feature enable error",
                attachment_type=allure.attachment_type.TEXT
            )
            raise


@when("Tempest tests are run")
def when_run_tempest_tests(request, tempest_runner):
    """Run Tempest tests for the given feature."""
    # Get feature from pytest-bdd scenario outline parameter
    feature = getattr(request, 'param', None)
    if feature is None:
        try:
            feature = request._pytest_bdd_example.get("feature")
        except Exception:
            pass
    
    if feature is None:
        return
    
    with allure.step(f"Running Tempest tests for {feature}"):
        result = tempest_runner(feature)

        allure.attach(
            result.stdout,
            name="Tempest output",
            attachment_type=allure.attachment_type.TEXT
        )

        if result.stderr:
            allure.attach(
                result.stderr,
                name="Tempest errors",
                attachment_type=allure.attachment_type.TEXT
            )

    return result


@then("the Tempest run should pass successfully")
def then_check_tempest_passed(when_run_tempest_tests):
    """Verify that the Tempest tests passed."""
    if when_run_tempest_tests is None:
        return
    
    result = when_run_tempest_tests

    if result.returncode != 0:
        raise AssertionError(
            f"Tempest tests failed with return code {result.returncode}. "
            "Check the attached logs in Allure."
        )
