import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_bdd import given
import allure
from unittest.mock import Mock

from defining_acceptance.provision_cloud import (
    get_testbed_with_ip_path,
    get_ssh_private_key_path,
    get_ssh_public_key_path,
    get_sunbeam_dev_path,
)


# Mock mode - set MOCK_MODE=1 to run tests without actual sunbeam
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"


def get_test_bed_file():
    """Get TEST_BED_FILE path, evaluated at runtime."""
    # First check if the environment variable is set
    if "TEST_BED_FILE" in os.environ:
        return Path(os.environ.get("TEST_BED_FILE"))
    
    # Check if there's a local testbed.yaml with IP in the defining-acceptance repo
    # Path(__file__) is tests/conftest.py, so .parent.parent gives us defining-acceptance/
    local_testbed = Path(__file__).parent.parent / "testbed.yaml"
    if local_testbed.exists():
        try:
            with open(local_testbed) as f:
                data = yaml.safe_load(f)
                machines = data.get("machines", [])
                if machines and "ip" in machines[0]:
                    return local_testbed
        except Exception:
            pass
    
    # Default to the testbed_with_ip.yaml from sunbeam-proxified-dev
    return get_testbed_with_ip_path()


def get_ssh_key_dir():
    """Get SSH_KEY_DIR path, evaluated at runtime."""
    # First check if the environment variable is set
    if "SSH_KEY_DIR" in os.environ:
        return Path(os.environ.get("SSH_KEY_DIR"))
    
    # Check if there's a local testbed.yaml with keys in defining-acceptance
    local_ssh_dir = Path(__file__).parent.parent
    priv_key = local_ssh_dir / "ssh_private_key"
    pub_key = local_ssh_dir / "ssh_public_key.pub"
    if priv_key.exists() and pub_key.exists():
        return local_ssh_dir
    
    # Default to sunbeam-proxified-dev directory
    return get_sunbeam_dev_path()


@pytest.fixture(scope="session")
def testbed():
    """Load testbed configuration from YAML file."""
    # In mock mode, return mock data
    if MOCK_MODE:
        return {
            "machines": [
                {
                    "hostname": "bm0",
                    "ip": "192.168.1.100",
                    "osd-devices": "bm0_osd0,bm0_osd1,bm0_osd2",
                    "external-networks": {"external": "restrictedbr0"},
                }
            ]
        }
    
    testbed_file = get_test_bed_file()
    if not testbed_file.exists():
        raise FileNotFoundError(
            f"Testbed file not found: {testbed_file}. "
            f"Set TEST_BED_FILE environment variable to point to the infrastructure YAML."
        )

    with open(testbed_file) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def ssh_keys():
    """Load SSH keys from the SSH_KEY_DIR."""
    # In mock mode, return mock data
    if MOCK_MODE:
        return {
            "public": "ssh-rsa MOCK_KEY test@example.com",
            "private": "-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----",
        }
    
    ssh_key_dir = get_ssh_key_dir()
    private_key_path = ssh_key_dir / "ssh_private_key"
    public_key_path = ssh_key_dir / "ssh_public_key.pub"

    if not private_key_path.exists() or not public_key_path.exists():
        raise FileNotFoundError(
            f"SSH keys not found in {ssh_key_dir}. "
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
    # In mock mode, return mock data without running actual commands
    if MOCK_MODE:
        machines = testbed.get("machines", [])
        primary_machine = machines[0]
        return {
            "infrastructure": testbed,
            "ssh_keys": ssh_keys,
            "primary_hostname": primary_machine.get("hostname", "mock-host"),
            "primary_ip": primary_machine.get("ip", "192.168.1.1"),
            "openrc_path": "demo-openrc",
        }
    
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
        """Enable a feature in the cloud using sunbeam enable."""
        # In mock mode, just return a mock result
        if MOCK_MODE:
            allure.step(f"[MOCK] Enabling feature: {name}")
            return Mock(returncode=0, stdout=f"[MOCK] Enabled {name}", stderr="")
        
        with allure.step(f"Enabling feature: {name}"):
            if name == "secrets":
                # Enable Vault first (dependency), then secrets
                # From docs: "The Vault feature is a dependency of the Secrets feature"
                vault_cmd = ["sunbeam", "enable", "vault"]
                result = subprocess.run(
                    vault_cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if result.returncode != 0:
                    allure.attach(
                        result.stdout,
                        name="Enable vault stdout",
                        attachment_type=allure.attachment_type.TEXT
                    )
                    allure.attach(
                        result.stderr,
                        name="Enable vault stderr",
                        attachment_type=allure.attachment_type.TEXT
                    )
                    # Continue to enable secrets anyway
                
                cmd = ["sunbeam", "enable", "secrets"]
            elif name == "caas":
                # From docs: "The secrets and load-balancer features are dependencies of the CaaS feature"
                # Enable loadbalancer first
                lb_cmd = ["sunbeam", "enable", "loadbalancer"]
                result = subprocess.run(
                    lb_cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if result.returncode != 0:
                    allure.attach(
                        result.stdout,
                        name="Enable loadbalancer stdout",
                        attachment_type=allure.attachment_type.TEXT
                    )
                    allure.attach(
                        result.stderr,
                        name="Enable loadbalancer stderr",
                        attachment_type=allure.attachment_type.TEXT
                    )
                
                cmd = ["sunbeam", "enable", "caas"]
            elif name == "loadbalancer":
                cmd = ["sunbeam", "enable", "loadbalancer"]
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
        # In mock mode, just return a mock result
        if MOCK_MODE:
            allure.step(f"[MOCK] Running Tempest tests for {feature or 'all'}")
            return Mock(returncode=0, stdout="[MOCK] Tempest tests passed", stderr="")
        
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
