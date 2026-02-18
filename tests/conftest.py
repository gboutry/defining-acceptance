import os
import shlex
import subprocess
import time
from pathlib import Path

import paramiko
import pytest
import yaml
from pytest_bdd import given
from unittest.mock import Mock

from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig, TestbedConfig


# Mock mode - set MOCK_MODE=1 to run tests without actual sunbeam
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"


def _load_testbed_for_collection(config) -> TestbedConfig:
    """Load testbed config during collection phase (before fixtures are available)."""
    testbed_file_opt = config.getoption("testbed_file", default=None)
    testbed_path = (
        Path(testbed_file_opt) if testbed_file_opt else Path.cwd() / "testbed.yaml"
    )
    if MOCK_MODE:
        return TestbedConfig.from_dict(
            {
                "machines": [
                    {
                        "hostname": "bm0",
                        "ip": "192.168.1.100",
                        "roles": ["control", "compute", "storage"],
                        "osd_devices": ["/dev/sdb"],
                        "external_networks": {"external": "restrictedbr0"},
                    }
                ],
                "deployment": {
                    "provider": "manual",
                    "topology": "single-node",
                    "channel": "2024.1/edge",
                },
                "features": [],
            }
        )
    if not testbed_path.exists():
        return TestbedConfig.from_dict(
            {
                "machines": [{"hostname": "unknown", "ip": "0.0.0.0", "roles": []}],
                "deployment": {
                    "provider": "manual",
                    "topology": "single-node",
                    "channel": "2024.1/edge",
                },
            }
        )
    return TestbedConfig.from_yaml(testbed_path)


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests whose marker requirements are not met by the testbed."""
    testbed = _load_testbed_for_collection(config)

    skip_rules = {
        "single_node": lambda tb: not tb.is_single_node,
        "single-node": lambda tb: not tb.is_single_node,
        "multi_node": lambda tb: not tb.is_multi_node,
        "multi-node": lambda tb: not tb.is_multi_node,
        "maas": lambda tb: not tb.is_maas,
        "external_juju": lambda tb: not tb.has_external_juju,
        "external-juju": lambda tb: not tb.has_external_juju,
        "proxy": lambda tb: not tb.has_proxy,
        "three_node": lambda tb: len(tb.machines) < 3,
        "three-node": lambda tb: len(tb.machines) < 3,
        # Provisioning marker - skip when cloud is already provisioned
        "provisioning": lambda tb: tb.is_provisioned,
        # Feature markers
        "secrets": lambda tb: not tb.has_feature("secrets"),
        "caas": lambda tb: not tb.has_feature("caas"),
        "loadbalancer": lambda tb: not tb.has_feature("loadbalancer"),
    }

    for item in items:
        for marker_name, should_skip in skip_rules.items():
            if item.get_closest_marker(marker_name) and should_skip(testbed):
                item.add_marker(
                    pytest.mark.skip(reason=f"Testbed does not satisfy @{marker_name}")
                )


def run_ssh_command(ip: str, command: list[str], ssh_key_path: str, timeout: int = 600):
    """
    Run a command on a remote host via SSH.

    Args:
        ip: Target machine IP address
        command: Command to run as list
        ssh_key_path: Path to SSH private key
        timeout: Command timeout in seconds

    Returns:
        subprocess.CompletedProcess result
    """
    command_text = " ".join(shlex.quote(part) for part in command)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=ip,
            username="ubuntu",
            key_filename=ssh_key_path,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )

        stdin, stdout, stderr = client.exec_command(command_text)
        channel = stdout.channel
        deadline = time.monotonic() + timeout

        while not channel.exit_status_ready():
            if time.monotonic() > deadline:
                channel.close()
                raise subprocess.TimeoutExpired(command, timeout)
            time.sleep(0.2)

        returncode = channel.recv_exit_status()
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")

        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )
    finally:
        client.close()


def pytest_addoption(parser):
    parser.addoption(
        "--testbed-file",
        action="store",
        default=None,
        metavar="PATH",
        help="Path to testbed YAML file (defaults to ./testbed.yaml).",
    )
    parser.addoption(
        "--ssh-private-key-file",
        action="store",
        default=None,
        metavar="PATH",
        help="Path to SSH private key file (defaults to ./ssh_private_key).",
    )


@pytest.fixture(scope="session")
def testbed(pytestconfig):
    """Load testbed configuration from YAML file."""
    if MOCK_MODE:
        return TestbedConfig.from_dict(
            {
                "machines": [
                    {
                        "hostname": "bm0",
                        "ip": "192.168.1.100",
                        "roles": ["control", "compute", "storage"],
                        "osd_devices": ["/dev/sdb"],
                        "external_networks": {"external": "restrictedbr0"},
                    }
                ],
                "deployment": {
                    "provider": "manual",
                    "topology": "single-node",
                    "channel": "2024.1/edge",
                },
                "features": [],
            }
        )

    configured_testbed_path = pytestconfig.getoption("testbed_file")
    testbed_file = (
        Path(configured_testbed_path)
        if configured_testbed_path
        else Path.cwd() / "testbed.yaml"
    )
    return TestbedConfig.from_yaml(testbed_file)


@pytest.fixture(scope="session")
def ssh_keys(pytestconfig):
    """Load SSH keys from pytest options."""
    # In mock mode, return mock data
    if MOCK_MODE:
        return {
            "private": "-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----",
            "private_path": "mock_ssh_private_key",
        }

    configured_private_key = pytestconfig.getoption("ssh_private_key_file")

    private_key_path = (
        Path(configured_private_key)
        if configured_private_key
        else Path.cwd() / "ssh_private_key"
    )

    if not private_key_path.exists():
        raise FileNotFoundError(
            f"SSH private key not found: {private_key_path}. "
            f"Use --ssh-private-key-file to provide credentials."
        )

    return {
        "private": private_key_path.read_text().strip(),
        "private_path": str(private_key_path),
    }


@pytest.fixture(scope="session")
def bootstrapped(testbed, ssh_keys):
    """
    Bootstrap the cloud using Sunbeam.

    This fixture:
    1. Reads infrastructure from testbed YAML file
    2. Reads SSH keys from the configured directory
    3. SSHs to the first machine and runs Sunbeam commands to bootstrap the cloud
    """
    # In mock mode, return mock data without running actual commands
    if MOCK_MODE:
        machines = testbed.machines
        primary_machine = machines[0]
        return {
            "infrastructure": testbed,
            "ssh_keys": ssh_keys,
            "primary_hostname": primary_machine.hostname,
            "primary_ip": primary_machine.ip,
            "openrc_path": "demo-openrc",
        }

    # Parse infrastructure from testbed
    machines = testbed.machines
    if not machines:
        raise RuntimeError("No machines found in testbed configuration")

    def machine_fqdn(machine: MachineConfig) -> str:
        return machine.fqdn or machine.hostname

    def machine_role(machine: MachineConfig, is_primary: bool) -> str:
        if machine.roles:
            return ",".join(machine.roles)
        return "control,compute,storage" if is_primary else "compute,storage"

    # Take the first machine as the primary for sunbeam bootstrap
    primary_machine = machines[0]
    hostname = primary_machine.hostname
    ip = primary_machine.ip
    primary_role = machine_role(primary_machine, is_primary=True)

    # Get SSH key path
    ssh_key_path = ssh_keys["private_path"]

    with report.step(f"Provisioning cloud on {hostname} ({ip})"):
        # Step 0: Install Sunbeam snap (if not already installed)
        with report.step("Installing Sunbeam snap"):
            install_cmd = [
                "sudo",
                "snap",
                "install",
                "openstack",
                "--channel",
                "2024.1/edge",
            ]
            result = run_ssh_command(
                ip=ip,
                command=install_cmd,
                ssh_key_path=ssh_key_path,
                timeout=600,
            )
            # Don't fail if already installed
            if result.returncode != 0 and "already installed" not in result.stdout:
                report.attach_text(result.stdout, "Install sunbeam stdout")
                report.attach_text(result.stderr, "Install sunbeam stderr")

        # Run node preparation script generated by sunbeam
        # Note: Don't use sudo - the script uses SUDO_ASKPASS internally
        with report.step("Running node preparation script"):
            prep_cmd = [
                "bash",
                "-c",
                "sunbeam prepare-node-script --bootstrap | bash -x",
            ]
            result = run_ssh_command(
                ip=ip,
                command=prep_cmd,
                ssh_key_path=ssh_key_path,
                timeout=600,
            )
            if result.returncode != 0:
                report.attach_text(result.stdout, "Prepare node script stdout")
                report.attach_text(result.stderr, "Prepare node script stderr")
                # Continue anyway - script might have already been run

        # Step 1: Bootstrap the cloud with Sunbeam
        # Using --accept-defaults for automated testing
        # Roles: control, compute, storage
        bootstrap_cmd = [
            "sunbeam",
            "cluster",
            "bootstrap",
            "--accept-defaults",
            "--role",
            primary_role,
            "--manifest",
            "/home/ubuntu/manifest.yaml",
        ]

        # Run bootstrap via SSH on target machine (takes ~20 minutes)
        with report.step("Bootstrapping Sunbeam cluster"):
            result = run_ssh_command(
                ip=ip,
                command=bootstrap_cmd,
                ssh_key_path=ssh_key_path,
                timeout=3600,  # 60 minutes timeout
            )

            if result.returncode != 0:
                report.attach_text(result.stdout, "Bootstrap stdout")
                report.attach_text(result.stderr, "Bootstrap stderr")
                raise RuntimeError(f"Sunbeam bootstrap failed: {result.stderr}")

            report.attach_text(result.stdout, "Bootstrap output")

        # Step 2: Configure the cloud for sample usage
        configure_cmd = [
            "sunbeam",
            "configure",
            "--accept-defaults",
            "--openrc",
            "demo-openrc",
        ]

        with report.step("Configuring Sunbeam cloud"):
            result = run_ssh_command(
                ip=ip,
                command=configure_cmd,
                ssh_key_path=ssh_key_path,
                timeout=300,  # 5 minutes timeout
            )

            if result.returncode != 0:
                report.attach_text(result.stdout, "Configure stdout")
                report.attach_text(result.stderr, "Configure stderr")
                raise RuntimeError(f"Sunbeam configure failed: {result.stderr}")

            report.attach_text(result.stdout, "Configure output")

        # Step 3: Join additional nodes declared in the testbed
        for joining_machine in machines[1:]:
            joining_hostname = joining_machine.hostname
            joining_ip = joining_machine.ip
            joining_fqdn = machine_fqdn(joining_machine)
            joining_role = machine_role(joining_machine, is_primary=False)
            token_path = f"/home/ubuntu/{joining_fqdn}.token"

            with report.step(
                f"Generating join token for {joining_hostname} ({joining_fqdn}) on {hostname}"
            ):
                add_cmd = [
                    "sunbeam",
                    "cluster",
                    "add",
                    joining_fqdn,
                    "-o",
                    token_path,
                ]
                add_result = run_ssh_command(
                    ip=ip,
                    command=add_cmd,
                    ssh_key_path=ssh_key_path,
                    timeout=300,
                )

                if add_result.returncode != 0:
                    report.attach_text(
                        add_result.stdout, f"Add token stdout ({joining_fqdn})"
                    )
                    report.attach_text(
                        add_result.stderr, f"Add token stderr ({joining_fqdn})"
                    )
                    raise RuntimeError(
                        f"Failed to generate join token for {joining_fqdn}: {add_result.stderr}"
                    )

            with report.step(
                f"Fetching join token for {joining_hostname} ({joining_fqdn})"
            ):
                token_result = run_ssh_command(
                    ip=ip,
                    command=["cat", token_path],
                    ssh_key_path=ssh_key_path,
                    timeout=60,
                )

                if token_result.returncode != 0 or not token_result.stdout.strip():
                    report.attach_text(
                        token_result.stdout, f"Token fetch stdout ({joining_fqdn})"
                    )
                    report.attach_text(
                        token_result.stderr, f"Token fetch stderr ({joining_fqdn})"
                    )
                    raise RuntimeError(
                        f"Failed to fetch join token for {joining_fqdn}: {token_result.stderr}"
                    )

                token_value = token_result.stdout.strip()

            with report.step(f"Joining node {joining_hostname} ({joining_ip})"):
                join_cmd = [
                    "bash",
                    "-lc",
                    f" sunbeam cluster join --role {joining_role} {token_value}",
                ]
                join_result = run_ssh_command(
                    ip=joining_ip,
                    command=join_cmd,
                    ssh_key_path=ssh_key_path,
                    timeout=3600,
                )

                if join_result.returncode != 0:
                    report.attach_text(
                        join_result.stdout, f"Join stdout ({joining_fqdn})"
                    )
                    report.attach_text(
                        join_result.stderr, f"Join stderr ({joining_fqdn})"
                    )
                    raise RuntimeError(
                        f"Failed to join node {joining_fqdn} ({joining_ip}): {join_result.stderr}"
                    )

                report.attach_text(join_result.stdout, f"Join output ({joining_fqdn})")

    # Return context for subsequent steps
    return {
        "infrastructure": testbed,
        "ssh_keys": ssh_keys,
        "primary_hostname": hostname,
        "primary_ip": ip,
        "openrc_path": "demo-openrc",
    }


@pytest.fixture(scope="session")
def enable_feature(bootstrapped):
    """Fixture to enable a feature in the cloud deployment."""

    def _feature_enabler(name: str):
        """Enable a feature in the cloud using sunbeam enable."""
        # In mock mode, just return a mock result
        if MOCK_MODE:
            report.note(f"[MOCK] Enabling feature: {name}")
            return Mock(returncode=0, stdout=f"[MOCK] Enabled {name}", stderr="")

        # Get connection info from bootstrapped fixture
        ip = bootstrapped["primary_ip"]
        ssh_key_path = bootstrapped["ssh_keys"]["private_path"]

        with report.step(f"Enabling feature: {name}"):
            if name == "secrets":
                # Enable Vault first (dependency), then secrets
                # From docs: "The Vault feature is a dependency of the Secrets feature"
                vault_cmd = ["sunbeam", "enable", "vault", "--devmode"]
                result = run_ssh_command(
                    ip=ip,
                    command=vault_cmd,
                    ssh_key_path=ssh_key_path,
                    timeout=600,
                )
                if result.returncode != 0:
                    report.attach_text(result.stdout, "Enable vault stdout")
                    report.attach_text(result.stderr, "Enable vault stderr")
                    # Continue to enable secrets anyway

                cmd = ["sunbeam", "enable", "secrets"]
            elif name == "caas":
                # From docs: "The secrets and load-balancer features are dependencies of the CaaS feature"
                # Enable loadbalancer first
                lb_cmd = ["sunbeam", "enable", "loadbalancer"]
                result = run_ssh_command(
                    ip=ip,
                    command=lb_cmd,
                    ssh_key_path=ssh_key_path,
                    timeout=600,
                )
                if result.returncode != 0:
                    report.attach_text(result.stdout, "Enable loadbalancer stdout")
                    report.attach_text(result.stderr, "Enable loadbalancer stderr")

                cmd = ["sunbeam", "enable", "caas"]
            elif name == "loadbalancer":
                cmd = ["sunbeam", "enable", "loadbalancer"]
            else:
                raise ValueError(f"Unknown feature: {name}")

            result = run_ssh_command(
                ip=ip,
                command=cmd,
                ssh_key_path=ssh_key_path,
                timeout=600,
            )

            if result.returncode != 0:
                report.attach_text(result.stdout, f"Enable {name} stdout")
                report.attach_text(result.stderr, f"Enable {name} stderr")
                raise RuntimeError(f"Failed to enable {name}: {result.stderr}")

            report.attach_text(result.stdout, f"Enable {name} output")

    return _feature_enabler


@pytest.fixture(scope="session")
def tempest_runner(bootstrapped):
    """Fixture to run Tempest tests."""

    def _runner(feature: str | None = None):
        """Run Tempest tests for the given feature."""
        # In mock mode, just return a mock result
        if MOCK_MODE:
            report.note(f"[MOCK] Running Tempest tests for {feature or 'all'}")
            return Mock(returncode=0, stdout="[MOCK] Tempest tests passed", stderr="")

        # Get connection info from bootstrapped fixture
        ip = bootstrapped["primary_ip"]
        ssh_key_path = bootstrapped["ssh_keys"]["private_path"]

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
            "--regex",
            pattern,
        ]

        with report.step(f"Running Tempest tests for {feature or 'all'}"):
            result = run_ssh_command(
                ip=ip,
                command=cmd,
                ssh_key_path=ssh_key_path,
                timeout=1800,  # 30 minutes
            )

            report.attach_text(result.stdout, "Tempest stdout")

            if result.stderr:
                report.attach_text(result.stderr, "Tempest stderr")

        return result

    return _runner


# Common step shared across all features
@given("the cloud is provisioned")
def provision_cloud(bootstrapped):
    """Verify that the cloud has been provisioned."""
    # The bootstrapped fixture already does the provisioning
    # This step just validates the cloud is ready
    with report.step("Verifying cloud is provisioned"):
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

        report.attach_text(result.stdout, "OpenStack endpoints")


def pytest_bdd_before_scenario(request, feature, scenario):
    """
    Dynamically map Gherkin feature files to Allure reporting structures.
    Runs immediately before each scenario executes.
    """

    # Add host information to Allure report if TEST_HOST is set
    test_host = os.environ.get("TEST_HOST")
    if test_host:
        report.label("host", test_host)
        report.label("environment", test_host)

    all_tags = set(feature.tags).union(set(scenario.tags))
    target_plans = ["security", "reliability", "operations", "performance"]

    for plan in target_plans:
        if plan in all_tags:
            plan_name = plan.capitalize()
            report.parent_suite(plan_name)
            break
    # allure.dynamic.title(scenario.name)
    report.suite(feature.name)
    report.sub_suite(scenario.name)
    report.description(feature.description)
