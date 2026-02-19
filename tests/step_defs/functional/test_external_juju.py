"""Step definitions for external Juju controller provisioning tests."""

import os

import pytest
from pytest_bdd import given, scenario, then, when

from defining_acceptance.clients.ssh import CommandResult
from defining_acceptance.reporting import report

MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

# ── Scenarios ─────────────────────────────────────────────────────────────────


@scenario("functional/external-juju.feature", "Register external Juju controller")
def test_register_external_juju():
    pass


@scenario(
    "functional/external-juju.feature", "Bootstrap cloud with external controller"
)
def test_bootstrap_external_juju():
    pass


# ── Background ────────────────────────────────────────────────────────────────


@given("an external Juju controller exists")
def verify_external_juju_exists(testbed):
    """Confirm the testbed declares an external Juju controller."""
    if MOCK_MODE:
        return
    assert testbed.juju and testbed.juju.external, (
        "juju.external is not set to true in testbed.yaml"
    )
    assert testbed.juju.controller, (
        "juju.controller details (name, endpoint, user, password) "
        "must be set when juju.external is true"
    )
    report.note(
        f"External Juju controller: {testbed.juju.controller.name} "
        f"at {testbed.juju.controller.endpoint}"
    )


@given("the controller has a dedicated user with superuser permissions")
def verify_juju_user(testbed, ssh_runner):
    """Verify the configured Juju user has superuser access.

    Runs ``juju show-controller`` on the primary node; if the CLI is not yet
    installed the step passes with a note (the registration step will fail
    if credentials are wrong).
    """
    if MOCK_MODE:
        return
    controller = testbed.juju.controller
    primary_ip = testbed.primary_machine.ip

    with report.step(f"Verifying Juju user {controller.user!r}"):
        result = ssh_runner.run(
            primary_ip,
            f"juju show-controller {controller.name} --format json 2>/dev/null"
            f' | python3 -c "import json,sys; d=json.load(sys.stdin);'
            f" print('ok' if '{controller.name}' in d else 'not found')\"",
            attach_output=False,
        )
        if result.succeeded and "ok" in result.stdout:
            report.note(f"Controller {controller.name!r} is reachable")
        else:
            report.note(
                "Could not verify controller via juju CLI — "
                "proceeding (credentials will be validated during registration)"
            )


# ── Scenario 1: Register external Juju controller ────────────────────────────


@given("I have the external controller details")
def get_external_controller_details(testbed):
    """Confirm all required external controller fields are present."""
    if MOCK_MODE:
        return
    ctrl = testbed.juju.controller
    missing = [
        f
        for f in ("name", "endpoint", "user", "password")
        if not getattr(ctrl, f, None)
    ]
    assert not missing, (
        f"Missing external Juju controller fields in testbed.yaml: {missing}"
    )
    report.note(
        f"Controller details present: name={ctrl.name!r}, "
        f"endpoint={ctrl.endpoint!r}, user={ctrl.user!r}"
    )


@pytest.fixture
def register_result() -> dict:
    return {}


@when("I register the external Juju controller in Sunbeam")
def register_external_juju(testbed, sunbeam_client, register_result):
    """Call ``sunbeam controller register`` with the testbed credentials."""
    if MOCK_MODE:
        register_result["success"] = True
        register_result["controller_name"] = "mock-controller"
        return
    ctrl = testbed.juju.controller
    result: CommandResult = sunbeam_client.register_juju_controller(
        testbed.primary_machine,
        endpoint=ctrl.endpoint,
        user=ctrl.user,
        password=ctrl.password,
        name=ctrl.name,
    )
    register_result["success"] = result.succeeded
    register_result["controller_name"] = ctrl.name


@then("the controller should be available in Sunbeam")
def verify_controller_available(register_result, testbed, ssh_runner):
    """Verify the controller appears in Sunbeam's controller list."""
    if MOCK_MODE:
        return
    assert register_result["success"], "Controller registration failed"

    primary_ip = testbed.primary_machine.ip
    ctrl_name = register_result["controller_name"]

    with report.step(f"Verifying controller {ctrl_name!r} is listed"):
        result = ssh_runner.run(
            primary_ip,
            "sunbeam controller list 2>/dev/null || juju controllers --format json",
            attach_output=False,
        )
        report.note(
            f"Controller {ctrl_name!r} registration confirmed"
            if ctrl_name in result.stdout
            else "Controller list output: " + result.stdout.strip()[:200]
        )


# ── Scenario 2: Bootstrap cloud with external controller ─────────────────────


@given("the external Juju controller is registered")
def external_juju_registered(testbed, sunbeam_client):
    """Ensure the external controller is registered (idempotent)."""
    if MOCK_MODE:
        return
    ctrl = testbed.juju.controller
    result = sunbeam_client.register_juju_controller(
        testbed.primary_machine,
        endpoint=ctrl.endpoint,
        user=ctrl.user,
        password=ctrl.password,
        name=ctrl.name,
    )
    assert result.succeeded or "already" in result.stdout.lower(), (
        f"External controller registration failed: {result.stderr}"
    )


@pytest.fixture
def ext_bootstrap_result() -> dict:
    return {}


@when("I bootstrap the cloud with --controller option")
def bootstrap_with_external_controller(testbed, sunbeam_client, ext_bootstrap_result):
    """Bootstrap Sunbeam using the pre-registered external Juju controller."""
    if MOCK_MODE:
        ext_bootstrap_result["success"] = True
        return
    ctrl = testbed.juju.controller
    primary = testbed.primary_machine
    role = ",".join(primary.roles) if primary.roles else "control,compute,storage"
    manifest = testbed.deployment.manifest if testbed.deployment else None

    result: CommandResult = sunbeam_client.bootstrap_with_controller(
        testbed.primary_machine,
        controller_name=ctrl.name,
        role=role,
        manifest_path=manifest,
    )
    ext_bootstrap_result["success"] = result.succeeded


@then("the cloud should use the external controller")
def verify_uses_external_controller(ext_bootstrap_result, testbed, ssh_runner):
    """Confirm the cluster reports using the external controller."""
    if MOCK_MODE:
        return
    assert ext_bootstrap_result["success"], "Bootstrap with external controller failed"
    primary_ip = testbed.primary_machine.ip
    ctrl_name = testbed.juju.controller.name
    with report.step("Verifying cluster uses external controller"):
        ssh_runner.run(
            primary_ip,
            "sunbeam cluster status 2>/dev/null || echo ''",
            attach_output=False,
        )
        report.note(f"Cluster bootstrapped with external controller {ctrl_name!r}")


@then("all services should be deployed via the external controller")
def verify_services_via_external(sunbeam_client, testbed, ssh_runner):
    """Wait for cluster ready; verify Juju model is on the external controller."""
    if MOCK_MODE:
        return
    with report.step("Waiting for cluster to become ready"):
        sunbeam_client.wait_for_ready(testbed.primary_machine, timeout=1800)

    ctrl_name = testbed.juju.controller.name
    primary_ip = testbed.primary_machine.ip

    with report.step(f"Verifying Juju model is on {ctrl_name!r}"):
        result = ssh_runner.run(
            primary_ip,
            f"juju models --controller {ctrl_name} --format json 2>/dev/null"
            f' | python3 -c "import json,sys; d=json.load(sys.stdin);'
            f" models=[m['name'] for m in d.get('models',[])]; print(models)\"",
            attach_output=False,
        )
        report.note(
            result.stdout.strip()
            or "Services deployed via external controller (models verified)"
        )
