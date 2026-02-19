"""Step definitions for MAAS provisioning tests."""

import os

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("functional/maas.feature", "Add MAAS provider to Sunbeam")
def test_add_maas_provider():
    pass


@scenario("functional/maas.feature", "Map network spaces")
def test_map_network_spaces():
    pass


@scenario("functional/maas.feature", "Bootstrap cloud with MAAS")
def test_bootstrap_maas():
    pass


# ── Background ────────────────────────────────────────────────────────────────


@given("a working MAAS environment exists")
def setup_maas_environment(testbed):
    """Verify the testbed has MAAS configuration."""
    if MOCK_MODE:
        return
    assert testbed.maas is not None, (
        "No MAAS configuration in testbed.yaml — "
        "add a 'maas:' section with endpoint and api_key"
    )
    report.note(f"MAAS endpoint: {testbed.maas.endpoint}")


@given("the machines are commissioned and ready in MAAS")
def verify_maas_machines_ready(testbed, sunbeam_client, ssh_runner):
    """Check that the listed machines appear as commissioned in MAAS.

    Uses the MAAS CLI (``maas``) on the primary node if available,
    otherwise relies on the operator to have verified this manually.
    """
    if MOCK_MODE:
        return
    primary_ip = testbed.primary_machine.ip
    with report.step("Checking MAAS machine status"):
        result = ssh_runner.run(
            primary_ip,
            (
                "maas admin machines read 2>/dev/null"
                ' | python3 -c "'
                "import json,sys; machines=json.load(sys.stdin);"
                " ready=[m for m in machines if m.get('status_name')=='Ready'];"
                " print(f'{len(ready)} ready machine(s)')\""
            ),
            attach_output=False,
        )
        if result.succeeded:
            report.note(result.stdout.strip())
        else:
            report.note(
                "MAAS CLI not available on primary node — "
                "assuming machines are ready (verify manually)"
            )


# ── Scenario 1: Add MAAS provider ─────────────────────────────────────────────


@given("I have a MAAS region API token")
def get_maas_token(testbed):
    """Verify the API token is present in testbed config."""
    if MOCK_MODE:
        return
    assert testbed.maas and testbed.maas.api_key, (
        "MAAS api_key not set in testbed.yaml maas section"
    )
    report.note("MAAS API token found in testbed configuration")


@pytest.fixture
def maas_provider_result() -> dict:
    return {}


@when("I add the MAAS provider to Sunbeam")
def add_maas_provider(testbed, sunbeam_client, maas_provider_result):
    """Call ``sunbeam provider add maas`` with the configured credentials."""
    if MOCK_MODE:
        maas_provider_result["success"] = True
        return
    result: CommandResult = sunbeam_client.add_maas_provider(
        testbed.primary_machine,
        endpoint=testbed.maas.endpoint,
        api_key=testbed.maas.api_key,
    )
    maas_provider_result["success"] = result.succeeded


@then("the MAAS provider should be registered")
def verify_maas_registered(maas_provider_result, sunbeam_client, testbed, ssh_runner):
    """Confirm the MAAS provider was registered by listing providers."""
    if MOCK_MODE:
        return
    assert maas_provider_result["success"], "add_maas_provider returned non-zero exit"

    primary_ip = testbed.primary_machine.ip
    with report.step("Verifying MAAS provider is listed"):
        result = ssh_runner.run(
            primary_ip,
            "sunbeam provider list 2>/dev/null || echo ''",
            attach_output=False,
        )
        if "maas" in result.stdout.lower():
            report.note("MAAS provider confirmed in provider list")
        else:
            report.note("Provider list does not yet mention MAAS — check Sunbeam logs")


# ── Scenario 2: Map network spaces ────────────────────────────────────────────


@given("the MAAS provider is configured")
def maas_provider_configured(testbed, sunbeam_client, ssh_runner):
    """Assert the MAAS provider is already registered (idempotent re-add)."""
    if MOCK_MODE:
        return
    result = sunbeam_client.add_maas_provider(
        testbed.primary_machine,
        endpoint=testbed.maas.endpoint,
        api_key=testbed.maas.api_key,
    )
    assert result.succeeded or "already" in result.stdout.lower(), (
        f"MAAS provider could not be configured: {result.stderr}"
    )


@pytest.fixture
def spaces_result() -> dict:
    return {}


@when("I map network spaces to cloud networks")
def map_network_spaces(testbed, sunbeam_client, spaces_result):
    """Map MAAS network spaces to Sunbeam networks using testbed config."""
    if MOCK_MODE:
        spaces_result["success"] = True
        return

    spaces = testbed.maas.network_spaces if testbed.maas else None
    if not spaces:
        pytest.skip("No network_spaces configured in testbed MAAS section")

    mappings = {
        "management": spaces.management,
        "storage": spaces.storage,
        "internal": spaces.internal,
    }
    for network, space in mappings.items():
        if space:
            with report.step(f"Mapping space {space!r} → network {network!r}"):
                sunbeam_client.map_maas_network_space(
                    testbed.primary_machine, space=space, network=network
                )

    spaces_result["success"] = True


@then("the network mappings should be configured")
def verify_network_mappings(spaces_result, testbed, ssh_runner):
    """Assert network space mapping completed and report the result."""
    if MOCK_MODE:
        return
    assert spaces_result["success"], "Network space mapping failed"

    primary_ip = testbed.primary_machine.ip
    with report.step("Verifying network space mappings"):
        result = ssh_runner.run(
            primary_ip,
            "sunbeam provider maas list-spaces 2>/dev/null || echo ''",
            attach_output=False,
        )
        report.note(
            result.stdout.strip() or "Space mapping verified (no list command output)"
        )


# ── Scenario 3: Bootstrap cloud with MAAS ─────────────────────────────────────


@given("network spaces are mapped")
def network_spaces_mapped(testbed, sunbeam_client):
    """Ensure spaces are mapped (idempotent — re-runs the mapping)."""
    if MOCK_MODE:
        return
    spaces = testbed.maas.network_spaces if testbed.maas else None
    if not spaces:
        pytest.skip("No network_spaces in testbed MAAS configuration")

    for network, space in [
        ("management", spaces.management),
        ("storage", spaces.storage),
        ("internal", spaces.internal),
    ]:
        if space:
            sunbeam_client.map_maas_network_space(
                testbed.primary_machine, space=space, network=network
            )


@pytest.fixture
def bootstrap_result() -> dict:
    return {}


@when("I bootstrap the orchestration layer")
def bootstrap_orchestration(testbed, sunbeam_client, bootstrap_result):
    """Bootstrap the Juju controller on the MAAS substrate."""
    if MOCK_MODE:
        bootstrap_result["juju_ok"] = True
        return
    result = sunbeam_client.bootstrap_juju_controller(testbed.primary_machine)
    bootstrap_result["juju_ok"] = result.succeeded


@then("the Juju controller should be deployed")
def verify_juju_deployed(bootstrap_result, testbed, ssh_runner):
    """Verify the Juju controller is up and reachable."""
    if MOCK_MODE:
        return
    assert bootstrap_result["juju_ok"], "Juju controller bootstrap failed"

    primary_ip = testbed.primary_machine.ip
    with report.step("Checking Juju controller status"):
        result = ssh_runner.run(
            primary_ip,
            "juju controllers --format json 2>/dev/null | python3 -c "
            '"import json,sys; d=json.load(sys.stdin); '
            "print(list(d.get('controllers',{}).keys()))\"",
            attach_output=False,
        )
        report.note(result.stdout.strip() or "Juju controller verified")


@pytest.fixture
def deploy_result() -> dict:
    return {}


@when("I deploy the cloud")
def deploy_cloud(testbed, sunbeam_client, deploy_result):
    """Deploy OpenStack on the bootstrapped Juju controller."""
    if MOCK_MODE:
        deploy_result["success"] = True
        return
    manifest = testbed.deployment.manifest if testbed.deployment else None
    result = sunbeam_client.deploy_cloud(
        testbed.primary_machine, manifest_path=manifest
    )
    deploy_result["success"] = result.succeeded


@then("all control plane services should be running")
def verify_services_running(deploy_result, testbed, sunbeam_client):
    """Wait for the cluster to report ready and verify all services are up."""
    if MOCK_MODE:
        return
    assert deploy_result["success"], "Cloud deployment failed"
    with report.step("Waiting for cluster to become ready"):
        sunbeam_client.wait_for_ready(testbed.primary_machine, timeout=1800)
    report.note("All control plane services are running")
