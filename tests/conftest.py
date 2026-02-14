import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_bdd import given
import allure


TEST_BED_FILE = Path(os.environ.get("TEST_BED_FILE", "testbed.yaml"))
SSH_KEY_DIR = Path(os.environ.get("SSH_KEY_DIR", "/tmp/sunbeam-ssh-keys"))


@pytest.fixture(scope="session")
def testbed():
    """Load testbed configuration from YAML file."""
    if not TEST_BED_FILE.exists():
        raise FileNotFoundError(
            f"Testbed file not found: {TEST_BED_FILE}. "
            f"Set TEST_BED_FILE environment variable to point to the infrastructure YAML."
        )

    with open(TEST_BED_FILE) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def ssh_keys():
    """Load SSH keys from the SSH_KEY_DIR."""
    private_key_path = SSH_KEY_DIR / "ssh_private_key"
    public_key_path = SSH_KEY_DIR / "ssh_public_key"

    if not private_key_path.exists() or not public_key_path.exists():
        raise FileNotFoundError(
            f"SSH keys not found in {SSH_KEY_DIR}. "
            f"Set SSH_KEY_DIR environment variable or ensure keys are in /tmp/sunbeam-ssh-keys/"
        )

    return {
        "public": public_key_path.read_text().strip(),
        "private": private_key_path.read_text().strip(),
    }


@pytest.fixture(scope="session")
def bootstrapped(testbed, ssh_keys):
    """
    Bootstrap the cloud using Sunbeam.

    This fixture:
    1. Reads infrastructure from testbed YAML file
    2. Reads SSH keys from the configured directory
    3. Runs Sunbeam commands to bootstrap the cloud
    """
    # Parse infrastructure from testbed
    machines = testbed.get("machines", [])
    if not machines:
        raise RuntimeError("No machines found in testbed configuration")

    # For now, we take the first machine as the primary
    # In multi-node scenarios, we'd need to handle differently
    primary_machine = machines[0]
    hostname = primary_machine["hostname"]
    ip = primary_machine["ip"]

    with allure.step(f"Provisioning cloud on {hostname} ({ip})"):
        # Step 1: Bootstrap the cloud with Sunbeam
        # Using --accept-defaults for automated testing
        # Roles: control, compute, storage
        bootstrap_cmd = [
            "sunbeam",
            "cluster",
            "bootstrap",
            "--accept-defaults",
            "--role", "control,compute,storage",
        ]

        # Run bootstrap (this takes ~20 minutes)
        with allure.step("Bootstrapping Sunbeam cluster"):
            result = subprocess.run(
                bootstrap_cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes timeout
            )

            if result.returncode != 0:
                allure.attach(
                    result.stdout,
                    name="Bootstrap stdout",
                    attachment_type=allure.attachment_type.TEXT
                )
                allure.attach(
                    result.stderr,
                    name="Bootstrap stderr",
                    attachment_type=allure.attachment_type.TEXT
                )
                raise RuntimeError(f"Sunbeam bootstrap failed: {result.stderr}")

            allure.attach(
                result.stdout,
                name="Bootstrap output",
                attachment_type=allure.attachment_type.TEXT
            )

        # Step 2: Configure the cloud for sample usage
        configure_cmd = [
            "sunbeam",
            "configure",
            "--accept-defaults",
            "--openrc", "demo-openrc",
        ]

        with allure.step("Configuring Sunbeam cloud"):
            result = subprocess.run(
                configure_cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
            )

            if result.returncode != 0:
                allure.attach(
                    result.stdout,
                    name="Configure stdout",
                    attachment_type=allure.attachment_type.TEXT
                )
                allure.attach(
                    result.stderr,
                    name="Configure stderr",
                    attachment_type=allure.attachment_type.TEXT
                )
                raise RuntimeError(f"Sunbeam configure failed: {result.stderr}")

            allure.attach(
                result.stdout,
                name="Configure output",
                attachment_type=allure.attachment_type.TEXT
            )

    # Return context for subsequent steps
    return {
        "infrastructure": testbed,
        "ssh_keys": ssh_keys,
        "primary_hostname": hostname,
        "primary_ip": ip,
        "openrc_path": "demo-openrc",
    }


@pytest.fixture(scope="session")
def enable_feature():
    """Fixture to enable a feature in the cloud deployment."""
    def _feature_enabler(name: str):
        """Enable a feature in the cloud."""
        # Features in OpenStack are typically enabled through:
        # 1. Sunbeam addons (sunbeam addons enable <addon>)
        # 2. Juju charms
        # 3. OpenStack configuration

        with allure.step(f"Enabling feature: {name}"):
            if name == "secrets":
                # Enable Vault for secrets
                cmd = ["sunbeam", "addon", "enable", "vault"]
            elif name == "caas":
                # Enable K8s for CaaS
                cmd = ["sunbeam", "cluster", "add-k8s", "--accept-defaults"]
            elif name == "loadbalancer":
                # Enable Octavia for load balancing
                cmd = ["sunbeam", "addon", "enable", "octavia"]
            else:
                raise ValueError(f"Unknown feature: {name}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:
                allure.attach(
                    result.stdout,
                    name=f"Enable {name} stdout",
                    attachment_type=allure.attachment_type.TEXT
                )
                allure.attach(
                    result.stderr,
                    name=f"Enable {name} stderr",
                    attachment_type=allure.attachment_type.TEXT
                )
                raise RuntimeError(f"Failed to enable {name}: {result.stderr}")

            allure.attach(
                result.stdout,
                name=f"Enable {name} output",
                attachment_type=allure.attachment_type.TEXT
            )

    return _feature_enabler


@pytest.fixture(scope="session")
def tempest_runner(bootstrapped):
    """Fixture to run Tempest tests."""
    def _runner(feature: str = None):
        """Run Tempest tests for the given feature."""
        # Run Tempest tests for the given feature
        # Tempest is typically run via:
        # 1. tempest run --regex <pattern>
        # 2. Or via openstack tox -e tempest

        # Map features to Tempest test patterns
        test_patterns = {
            "secrets": "barbican",
            "caas": "k8s",
            "loadbalancer": "octavia",
        }

        pattern = test_patterns.get(feature, feature) if feature else ".*"

        cmd = [
            "tempest",
            "run",
            "--regex", pattern,
        ]

        with allure.step(f"Running Tempest tests for {feature or 'all'}"):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes
            )

            allure.attach(
                result.stdout,
                name="Tempest stdout",
                attachment_type=allure.attachment_type.TEXT
            )

            if result.stderr:
                allure.attach(
                    result.stderr,
                    name="Tempest stderr",
                    attachment_type=allure.attachment_type.TEXT
                )

        return result

    return _runner


# Common step shared across all features
@given("the cloud is provisionned")
def provision_cloud(bootstrapped):
    """Verify that the cloud has been provisioned."""
    # The bootstrapped fixture already does the provisioning
    # This step just validates the cloud is ready
    with allure.step("Verifying cloud is provisioned"):
        # Check that we can source the openrc and run openstack commands
        openrc_path = bootstrapped.get("openrc_path", "demo-openrc")

        result = subprocess.run(
            f"source {openrc_path} && openstack endpoint list",
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Cloud not ready: {result.stderr}")

        allure.attach(
            result.stdout,
            name="OpenStack endpoints",
            attachment_type=allure.attachment_type.TEXT
        )


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
    # allure.dynamic.title(scenario.name)
    allure.dynamic.suite(feature.name)
    allure.dynamic.sub_suite(scenario.name)
    allure.dynamic.description(feature.description)
