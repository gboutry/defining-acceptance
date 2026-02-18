"""Step definitions for the operations test suite."""
import os

import pytest
from pytest_bdd import given, parsers, then, when



from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"


# "the cloud is provisioned" is defined in tests/conftest.py and applies here.


@given("the cloud is configured for sample usage")
def cloud_configured(openstack_client):
    """Verify the cloud has the basic resources needed to run workloads.

    Checks that at least one flavor, image, and network are present —
    the resources created by ``sunbeam configure`` during bootstrap.
    """
    if MOCK_MODE:
        return
    with report.step("Verifying cloud is configured for sample usage"):
        flavors = openstack_client.flavor_list()
        assert flavors, "No flavors found — run 'sunbeam configure' first"

        images = openstack_client.image_list()
        assert images, "No images found — run 'sunbeam configure' first"

        networks = openstack_client.network_list()
        assert networks, "No networks found — run 'sunbeam configure' first"

        report.note(
            f"Found {len(flavors)} flavor(s), "
            f"{len(images)} image(s), "
            f"{len(networks)} network(s)"
        )


@given(parsers.parse('the feature "{feature}" is enabled'))
def given_feature_enabled(enable_feature, testbed, feature):
    """Enable the named Sunbeam feature, or skip if not declared in the testbed."""
    if not testbed.has_feature(feature):
        pytest.skip(f"Feature '{feature}' is not enabled in this testbed")
    enable_feature(feature)


# tempest_result is a function-scoped mutable container used to pass the
# CommandResult from the @when step into the @then step without relying on
# return-value injection (which requires the @pytest.fixture + @when double-
# decoration pattern that conflicts with Scenario Outline parameterisation).
@pytest.fixture
def tempest_result() -> dict:
    return {}


@when(parsers.parse('I run Tempest tests for the feature "{feature}"'))
def when_run_tempest_tests(tempest_runner, tempest_result, feature):
    """Execute the Tempest test suite for the given feature."""
    with report.step(f"Running Tempest tests for '{feature}'"):
        result: CommandResult = tempest_runner(feature)
        tempest_result["result"] = result
        tempest_result["feature"] = feature


@then("the Tempest run should pass successfully")
def then_check_tempest_passed(tempest_result):
    """Assert that the Tempest run produced a zero exit code."""
    result: CommandResult = tempest_result["result"]
    feature = tempest_result["feature"]
    assert result.succeeded, (
        f"Tempest tests for '{feature}' failed (rc={result.returncode}).\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
