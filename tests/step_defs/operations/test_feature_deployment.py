import subprocess

import pytest
from pytest_bdd import scenarios, given, when, then, parsers
import allure


# Load all scenario outlines from the feature file
scenarios("operations/deployments.feature")


@given(parsers.parse('the feature "{feature}" is enabled'))
def enable_feature_step(enable_feature, feature):
    """Enable a feature in the cloud deployment."""
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


@pytest.fixture
@when(parsers.parse('I run the Tempest tests for the "{feature}"'))
def run_tempest_test(tempest_runner, feature):
    """Run Tempest tests for the given feature."""
    with allure.step(f"Running Tempest tests for {feature}"):
        result = tempest_runner(feature)

        # Attach output to Allure
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
def check_tempest_passed(run_tempest_test):
    """Verify that the Tempest tests passed."""
    result = run_tempest_test

    # Check the return code
    if result.returncode != 0:
        raise AssertionError(
            f"Tempest tests failed with return code {result.returncode}. "
            "Check the attached logs in Allure."
        )
