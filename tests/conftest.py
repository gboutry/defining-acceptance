import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_bdd import given

from defining_acceptance.clients import OpenStackClient, SSHRunner, SunbeamClient
from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig, TestbedConfig


# Set MOCK_MODE=1 to run tests without real infrastructure.
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

_MOCK_TESTBED_DICT = {
    "machines": [
        {
            "hostname": "bm0",
            "ip": "192.168.1.100",
            "roles": ["control", "compute", "storage"],
            "osd_devices": ["/dev/disks-by-id/sdb-id"],
            "external_networks": {"external-net": "enp6s0"},
        }
    ],
    "deployment": {
        "provider": "manual",
        "topology": "single-node",
        "channel": "2024.1/edge",
    },
    "features": [],
}


# ── Collection-time helpers ───────────────────────────────────────────────────


def _load_testbed_for_collection(config) -> TestbedConfig:
    """Load testbed during pytest collection (before fixtures are available)."""
    testbed_file_opt = config.getoption("testbed_file", default=None)
    testbed_path = (
        Path(testbed_file_opt) if testbed_file_opt else Path.cwd() / "testbed.yaml"
    )
    if MOCK_MODE:
        return TestbedConfig.from_dict(_MOCK_TESTBED_DICT)
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
        "provisioning": lambda tb: tb.is_provisioned,
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


# ── CLI options ───────────────────────────────────────────────────────────────


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


# ── Session fixtures: infrastructure ─────────────────────────────────────────


@pytest.fixture(scope="session")
def testbed(pytestconfig) -> TestbedConfig:
    """Parsed testbed configuration."""
    if MOCK_MODE:
        return TestbedConfig.from_dict(_MOCK_TESTBED_DICT)
    configured_path = pytestconfig.getoption("testbed_file")
    testbed_file = (
        Path(configured_path) if configured_path else Path.cwd() / "testbed.yaml"
    )
    return TestbedConfig.from_yaml(testbed_file)


@pytest.fixture(scope="session")
def ssh_private_key_path(pytestconfig, testbed) -> str:
    """Resolved path to the SSH private key as a string."""
    if MOCK_MODE:
        return "mock_ssh_private_key"
    cli_opt = pytestconfig.getoption("ssh_private_key_file")
    if cli_opt:
        return cli_opt
    if testbed.ssh and testbed.ssh.private_key:
        return testbed.ssh.private_key
    default = Path.cwd() / "ssh_private_key"
    if not default.exists():
        raise FileNotFoundError(
            f"SSH private key not found at {default}. "
            "Use --ssh-private-key-file or set ssh.private_key in testbed.yaml."
        )
    return str(default)


@pytest.fixture(scope="session")
def ssh_runner(testbed, ssh_private_key_path) -> SSHRunner:
    """SSHRunner configured for the testbed."""
    if MOCK_MODE:
        mock = MagicMock(spec=SSHRunner)
        mock.run.return_value = CommandResult(
            command="mock", returncode=0, stdout="mock output", stderr=""
        )
        mock.read_file.return_value = "mock-token"
        return mock
    user = (testbed.ssh.user if testbed.ssh else None) or "ubuntu"
    return SSHRunner(user=user, private_key_path=ssh_private_key_path)


@pytest.fixture(scope="session")
def sunbeam_client(ssh_runner, testbed) -> SunbeamClient:
    """SunbeamClient bound to the primary control machine."""
    if MOCK_MODE:
        return MagicMock(spec=SunbeamClient)
    return SunbeamClient(ssh=ssh_runner, primary=testbed.primary_machine)


@pytest.fixture(scope="session")
def openstack_client(ssh_runner, testbed) -> OpenStackClient:
    """OpenStackClient bound to the primary control machine."""
    if MOCK_MODE:
        return MagicMock(spec=OpenStackClient)
    return OpenStackClient(
        ssh=ssh_runner,
        primary=testbed.primary_machine,
        openrc_path="demo-openrc",
    )


# ── Session fixture: provisioning ─────────────────────────────────────────────


def _machine_role(machine: MachineConfig, is_primary: bool) -> str:
    if machine.roles:
        return ",".join(machine.roles)
    return "control,compute,storage" if is_primary else "compute,storage"


@pytest.fixture(scope="session")
def bootstrapped(testbed, sunbeam_client):
    """Bootstrap the Sunbeam cluster.

    Installs the snap, runs prepare-node, bootstraps the primary machine, then
    joins every additional machine listed in the testbed.  Idempotent in the
    sense that snap install and prepare-node tolerate being run twice.

    Skip automatically when ``deployment.provisioned: true`` is set.
    """
    if MOCK_MODE:
        return

    channel = testbed.deployment.channel if testbed.deployment else "2024.1/edge"
    manifest = testbed.deployment.manifest if testbed.deployment else None
    primary = testbed.primary_machine

    with report.step(f"Bootstrapping cloud on {primary.hostname} ({primary.ip})"):
        sunbeam_client.install_snap(channel)
        sunbeam_client.prepare_node(primary)
        sunbeam_client.bootstrap(
            role=_machine_role(primary, is_primary=True),
            manifest_path=manifest,
        )
        sunbeam_client.configure()

        for machine in testbed.machines[1:]:
            fqdn = machine.fqdn or machine.hostname
            token_path = f"/home/ubuntu/{fqdn}.token"
            token = sunbeam_client.generate_join_token(fqdn, token_path)
            sunbeam_client.join(
                machine=machine,
                role=_machine_role(machine, is_primary=False),
                token=token,
            )


# ── Session fixture: feature enablement ──────────────────────────────────────

# Maps a feature name to the dependency features that must be enabled first.
_FEATURE_DEPS: dict[str, list[str]] = {
    "secrets": ["vault"],
    "caas": ["loadbalancer"],
}


@pytest.fixture(scope="session")
def enable_feature(bootstrapped, sunbeam_client):
    """Return a callable that enables a named Sunbeam feature (with its deps)."""

    enabled: set[str] = set()

    def _enable(name: str) -> None:
        if name in enabled:
            return
        if MOCK_MODE:
            report.note(f"[MOCK] Enabling feature: {name}")
            enabled.add(name)
            return
        for dep in _FEATURE_DEPS.get(name, []):
            _enable(dep)
        sunbeam_client.enable(name)
        enabled.add(name)

    return _enable


# ── Session fixture: Tempest ──────────────────────────────────────────────────

_TEMPEST_PATTERNS: dict[str, str] = {
    "secrets": "barbican",
    "caas": "k8s",
    "loadbalancer": "octavia",
}


@pytest.fixture(scope="session")
def tempest_runner(bootstrapped, ssh_runner, testbed):
    """Return a callable that runs Tempest tests for a given feature."""

    def _run(feature: str | None = None) -> CommandResult:
        if MOCK_MODE:
            report.note(f"[MOCK] Running Tempest for {feature or 'all'}")
            return CommandResult(
                command="mock-tempest", returncode=0, stdout="All tests passed", stderr=""
            )
        pattern = _TEMPEST_PATTERNS.get(feature, feature) if feature else ".*"
        with report.step(f"Running Tempest tests (pattern={pattern!r})"):
            return ssh_runner.run(
                testbed.primary_machine.ip,
                ["tempest", "run", "--regex", pattern],
                timeout=1800,
            ).check()

    return _run


# ── Shared step definitions ───────────────────────────────────────────────────


@given("the cloud is provisioned")
def provision_cloud(bootstrapped, openstack_client):
    """Verify the cloud is up by listing service endpoints."""
    if MOCK_MODE:
        return
    with report.step("Verifying cloud is provisioned"):
        endpoints = openstack_client.endpoint_list()
        assert endpoints, "No service endpoints found — cloud may not be configured"
        report.attach_text(
            "\n".join(e.get("URL", "") for e in endpoints), "Service endpoints"
        )


# ── Allure reporting hook ─────────────────────────────────────────────────────


def pytest_bdd_before_scenario(request, feature, scenario):
    """Map Gherkin tags to Allure suite hierarchy."""
    test_host = os.environ.get("TEST_HOST")
    if test_host:
        report.label("host", test_host)
        report.label("environment", test_host)

    all_tags = set(feature.tags) | set(scenario.tags)
    for plan in ("security", "reliability", "operations", "performance", "provisioning"):
        if plan in all_tags:
            report.parent_suite(plan.capitalize())
            break

    report.suite(feature.name)
    report.sub_suite(scenario.name)
    report.description(feature.description)
