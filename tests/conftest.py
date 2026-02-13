import pytest
from pytest_bdd import given
import allure
import os


@pytest.fixture(scope="session")
def bootstrapped():
    pass


@pytest.fixture(scope="session")
def enable_feature():
    def _feature_enabler(name: str):
        # Logic to enable the feature in your deployment tool's configuration
        pass

    return _feature_enabler


@pytest.fixture(scope="session")
def tempest_runner():
    # This fixture would contain logic to run Tempest, perhaps via subprocess
    # or by invoking a Python API if available.
    def _runner():
        pass

    return _runner


# Common step shared across all features
@given("the cloud is provisionned")
def provision_cloud(bootstrapped):
    # Logic to provision cloud (e.g., triggering Ansible/Terraform)
    pass


def pytest_bdd_before_scenario(request, feature, scenario):
    """
    Dynamically map Gherkin feature files to Allure reporting structures.
    Runs immediately before each scenario executes.
    """
    
    # Add host information to Allure report if TEST_HOST is set
    test_host = os.environ.get('TEST_HOST')
    if test_host:
        allure.dynamic.label('host', test_host)
        allure.dynamic.label('environment', test_host)

    all_tags = set(feature.tags).union(set(scenario.tags))
    target_plans = ["security", "reliability", "operations", "performance"]

    for plan in target_plans:
        if plan in all_tags:
            plan_name = plan.capitalize()
            allure.dynamic.parent_suite(plan_name)
            break
    if plan == "security":
        # For security tests, we might want to add a specific label for severity
        allure.dynamic.severity(allure.severity_level.CRITICAL)
        raise Exception("Simulated failure")
    # allure.dynamic.title(scenario.name)
    allure.dynamic.suite(feature.name)
    allure.dynamic.sub_suite(scenario.name)
    allure.dynamic.description(feature.description)
