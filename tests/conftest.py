import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
import typing
from unittest.mock import MagicMock

from defining_acceptance.utils import DeferStack
import pytest
from pytest_bdd import given

from defining_acceptance.clients import OpenStackClient, SSHRunner, SunbeamClient
from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report
from defining_acceptance.testbed import MachineConfig, TestbedConfig


# Set MOCK_MODE=1 to run tests without real infrastructure.
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# Set KEEP_TMP=1 to preserve the session temp directory after the run.
KEEP_TMP = os.environ.get("KEEP_TMP", "0") == "1"

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


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
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
        "provisioning": lambda tb: tb.is_provisioned,
        "three_node": lambda tb: len(tb.machines) < 3,
        "three-node": lambda tb: len(tb.machines) < 3,
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


# ── Test Observer integration ─────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register the Test Observer plugin when TO_URL is set."""
    from defining_acceptance.observer import create_plugin

    plugin = create_plugin()
    if plugin is not None:
        config.pluginmanager.register(plugin, "test-observer")


# ── CLI options ───────────────────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
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
def session_tmp_dir() -> Generator[Path, None, None]:
    """Session-scoped temp directory for command output logs.

    Deleted automatically at session end unless ``KEEP_TMP=1`` is set.
    """
    tmp = Path(tempfile.mkdtemp(prefix="defining-acceptance-"))
    try:
        yield tmp
    finally:
        if KEEP_TMP:
            print(f"\nSession tmp dir preserved: {tmp}", flush=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def testbed(pytestconfig: pytest.Config) -> TestbedConfig:
    """Parsed testbed configuration."""
    if MOCK_MODE:
        return TestbedConfig.from_dict(_MOCK_TESTBED_DICT)
    configured_path = pytestconfig.getoption("testbed_file")
    testbed_file = (
        Path(configured_path) if configured_path else Path.cwd() / "testbed.yaml"
    )
    return TestbedConfig.from_yaml(testbed_file)


@pytest.fixture(scope="session")
def ssh_private_key_path(pytestconfig: pytest.Config, testbed: TestbedConfig) -> str:
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
def ssh_runner(
    testbed: TestbedConfig, ssh_private_key_path: str, session_tmp_dir: Path
) -> SSHRunner:
    """SSHRunner configured for the testbed."""
    if MOCK_MODE:
        mock = MagicMock(spec=SSHRunner)
        mock.run.return_value = CommandResult(
            command="mock", returncode=0, stdout="mock output", stderr=""
        )
        mock.read_file.return_value = "mock-token"
        return mock
    user = (testbed.ssh.user if testbed.ssh else None) or "ubuntu"
    return SSHRunner(
        user=user, private_key_path=ssh_private_key_path, tmp_dir=session_tmp_dir
    )


@pytest.fixture(scope="session")
def sunbeam_client(ssh_runner: SSHRunner, testbed: TestbedConfig) -> SunbeamClient:
    """SunbeamClient bound to the primary control machine."""
    if MOCK_MODE:
        return MagicMock(spec=SunbeamClient)
    return SunbeamClient(ssh=ssh_runner)


@pytest.fixture(scope="session")
def primary_machine(testbed: TestbedConfig) -> MachineConfig:
    """The primary control machine from the testbed configuration."""
    return testbed.primary_machine


@pytest.fixture(scope="session")
def demo_os_runner(
    testbed: TestbedConfig,
    ssh_private_key_path: str,
    session_tmp_dir: Path,
    primary_machine: MachineConfig,
) -> OpenStackClient:
    """OpenStackClient for the demo (regular) cloud user (OS_CLOUD=sunbeam)."""
    if MOCK_MODE:
        return MagicMock(spec=OpenStackClient)
    user = (testbed.ssh.user if testbed.ssh else None) or "ubuntu"
    runner = SSHRunner(
        user=user,
        private_key_path=ssh_private_key_path,
        tmp_dir=session_tmp_dir,
        env={"OS_CLOUD": "sunbeam"},
    )
    return OpenStackClient(ssh=runner, machine=primary_machine)


@pytest.fixture(scope="session")
def admin_os_runner(
    testbed: TestbedConfig,
    ssh_private_key_path: str,
    session_tmp_dir: Path,
    primary_machine: MachineConfig,
) -> OpenStackClient:
    """OpenStackClient for the admin (superuser) cloud user (OS_CLOUD=sunbeam-admin)."""
    if MOCK_MODE:
        return MagicMock(spec=OpenStackClient)
    user = (testbed.ssh.user if testbed.ssh else None) or "ubuntu"
    runner = SSHRunner(
        user=user,
        private_key_path=ssh_private_key_path,
        tmp_dir=session_tmp_dir,
        env={"OS_CLOUD": "sunbeam-admin"},
    )
    return OpenStackClient(ssh=runner, machine=primary_machine)


# ── Session fixture: provisioning ─────────────────────────────────────────────


def _machine_role(machine: MachineConfig, is_primary: bool) -> str:
    if machine.roles:
        return ",".join(machine.roles)
    return "control,compute,storage" if is_primary else "compute,storage"


@pytest.fixture(scope="session")
def bootstrapped(testbed: TestbedConfig, sunbeam_client: SunbeamClient) -> None:
    """Bootstrap the Sunbeam cluster.

    Installs the snap, runs prepare-node, bootstraps the primary machine, then
    joins every additional machine listed in the testbed.  Idempotent in the
    sense that snap install and prepare-node tolerate being run twice.

    Skip automatically when ``deployment.provisioned: true`` is set.
    """
    if MOCK_MODE or (testbed.deployment and testbed.deployment.provisioned):
        return

    channel = testbed.deployment.channel if testbed.deployment else "2024.1/edge"
    revision = testbed.deployment.revision if testbed.deployment else None
    manifest = testbed.deployment.manifest if testbed.deployment else None
    primary = testbed.primary_machine

    with report.step(f"Bootstrapping cloud on {primary.hostname} ({primary.ip})"):
        sunbeam_client.install_snap(primary, channel=channel, revision=revision)
        sunbeam_client.prepare_node(primary, bootstrap=True)
        sunbeam_client.bootstrap(
            primary,
            role=_machine_role(primary, is_primary=True),
            manifest_path=manifest,
        )
        sunbeam_client.configure(primary)
        sunbeam_client.cloud_config(primary)

    for machine in testbed.machines[1:]:
        with report.step(
            f"Joining machine {machine.hostname} ({machine.ip}) to cluster"
        ):
            sunbeam_client.install_snap(machine, channel=channel, revision=revision)
            sunbeam_client.prepare_node(machine)
            fqdn = machine.fqdn or machine.hostname
            token_path = f"/home/ubuntu/{fqdn}.token"
            token = sunbeam_client.generate_join_token(primary, fqdn, token_path)
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
def enable_feature(
    bootstrapped: None, sunbeam_client: SunbeamClient, primary_machine: MachineConfig
) -> typing.Callable[[str], None]:
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
        sunbeam_client.enable(primary_machine, name)
        enabled.add(name)

    return _enable


# ── Session fixture: Tempest ──────────────────────────────────────────────────

_TEMPEST_PATTERNS: dict[str, str] = {
    "secrets": "barbican",
    "caas": "k8s",
    "loadbalancer": "octavia",
}


@pytest.fixture(scope="session")
def tempest_runner(
    bootstrapped: None, ssh_runner: SSHRunner, testbed: TestbedConfig
) -> typing.Callable[[str | None], CommandResult]:
    """Return a callable that runs Tempest tests for a given feature."""

    def _run(feature: str | None = None) -> CommandResult:
        if MOCK_MODE:
            report.note(f"[MOCK] Running Tempest for {feature or 'all'}")
            return CommandResult(
                command="mock-tempest",
                returncode=0,
                stdout="All tests passed",
                stderr="",
            )
        pattern = _TEMPEST_PATTERNS.get(feature, feature) if feature else ".*"
        with report.step(f"Running Tempest tests (pattern={pattern!r})"):
            return ssh_runner.run(
                testbed.primary_machine.ip,
                ["tempest", "run", "--regex", pattern],
                timeout=1800,
            ).check()

    return _run


@pytest.fixture()
def defer(request: pytest.FixtureRequest) -> DeferStack:
    stack = DeferStack()
    request.addfinalizer(stack.cleanup)
    return stack


# ── Shared step definitions ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def is_configured_for_sample_usage(demo_os_runner: OpenStackClient) -> bool:
    """Check if the cloud has the basic resources needed to run workloads."""
    if MOCK_MODE:
        return True
    with report.step("Verifying cloud is configured for sample usage"):
        flavors = demo_os_runner.flavor_list()
        assert flavors, "No flavors found — run 'sunbeam configure' first"

        images = demo_os_runner.image_list()
        assert images, "No images found — run 'sunbeam configure' first"

        networks = demo_os_runner.network_list()
        assert networks, "No networks found — run 'sunbeam configure' first"

        report.note(
            f"Found {len(flavors)} flavor(s), "
            f"{len(images)} image(s), "
            f"{len(networks)} network(s)"
        )
    return True


@given("the cloud is configured for sample usage")
def cloud_configured(is_configured_for_sample_usage: bool) -> None:
    """Verify the cloud has the basic resources needed to run workloads."""
    assert is_configured_for_sample_usage, "Cloud is not configured for sample usage"


@pytest.fixture(scope="session")
def is_provisioned(bootstrapped: None, admin_os_runner: OpenStackClient) -> bool:
    """Check if the cloud is provisioned (bootstrapped)."""
    if MOCK_MODE:
        return True
    with report.step("Verifying cloud is provisioned"):
        endpoints = admin_os_runner.endpoint_list()
        assert endpoints, "No service endpoints found — cloud may not be configured"
        report.attach_text(
            "\n".join(e.get("URL", "") for e in endpoints), "Service endpoints"
        )
    return True


@given("the cloud is provisioned")
def provision_cloud(is_provisioned) -> None:
    """Verify the cloud is up by listing service endpoints."""
    assert is_provisioned, "Cloud is not provisioned"
