"""Collect deployment debug artifacts from testbed machines."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from defining_acceptance.clients.ssh import SSHRunner
from defining_acceptance.testbed import MachineConfig, TestbedConfig

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]")


def _sanitize(value: str) -> str:
    cleaned = _SAFE_NAME.sub("_", value)
    return cleaned.strip("_") or "unknown"


def _write_result(base_dir: Path, name: str, stdout: str, stderr: str) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / f"{name}.stdout.log").write_text(stdout, encoding="utf-8")
    (base_dir / f"{name}.stderr.log").write_text(stderr, encoding="utf-8")


def _collect_sos_for_machine(
    ssh: SSHRunner,
    machine: MachineConfig,
    artifacts_dir: Path,
) -> tuple[str, bool, str]:
    host_label = _sanitize(machine.hostname)
    host_dir = artifacts_dir / "sos" / host_label
    host_dir.mkdir(parents=True, exist_ok=True)

    update_index = ssh.run(
        machine.ip,
        "sudo DEBIAN_FRONTEND=noninteractive apt-get update -y",
        timeout=300,
        attach_output=False,
    )
    _write_result(host_dir, "apt-update", update_index.stdout, update_index.stderr)
    if update_index.returncode != 0:
        return (machine.hostname, False, "failed to update apt index")

    install = ssh.run(
        machine.ip,
        "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y sosreport",
        timeout=1200,
        attach_output=False,
    )
    _write_result(host_dir, "install-sosreport", install.stdout, install.stderr)
    if install.returncode != 0:
        return (machine.hostname, False, "failed to install sosreport")

    sos = ssh.run(
        machine.ip,
        f"sudo sos report --batch --all-logs --name {_sanitize(machine.hostname)}",
        timeout=3600,
        attach_output=False,
    )
    _write_result(host_dir, "sos-report", sos.stdout, sos.stderr)
    if sos.returncode != 0:
        return (machine.hostname, False, "failed to run sos report")

    archive = ssh.run(
        machine.ip,
        "sudo ls -1t /tmp/sosreport-*.tar* 2>/dev/null",
        timeout=60,
        attach_output=False,
    )
    _write_result(host_dir, "sos-archive-path", archive.stdout, archive.stderr)
    remote_archives = archive.stdout.strip()
    if archive.returncode != 0 or not remote_archives:
        return (machine.hostname, False, "could not locate sos archive")

    archive_files = []
    for line in remote_archives.splitlines():
        local_archive = host_dir / Path(line).name
        archive_files.append(local_archive)
        ssh.download_file(
            machine.ip,
            line,
            local_archive,
        )
    return (machine.hostname, True, ", ".join(str(f) for f in archive_files))


def _list_models(ssh: SSHRunner, machine: MachineConfig) -> list[str]:
    models_cmd = ssh.run(
        machine.ip,
        "juju models --format json",
        timeout=120,
        attach_output=False,
    )
    if models_cmd.returncode != 0:
        return []

    try:
        payload = json.loads(models_cmd.stdout)
    except json.JSONDecodeError:
        return []

    models: list[str] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        short_name = item.get("short-name")
        if isinstance(short_name, str) and short_name:
            models.append(short_name)
            continue
        model_name = item.get("name")
        if isinstance(model_name, str) and model_name:
            models.append(model_name)

    return sorted(set(models))


def _list_units_for_model(
    ssh: SSHRunner,
    machine: MachineConfig,
    model: str,
) -> list[str]:
    status_json = ssh.run(
        machine.ip,
        f"juju status -m {model} --format json",
        timeout=240,
        attach_output=False,
    )
    if status_json.returncode != 0:
        return []

    try:
        payload = json.loads(status_json.stdout)
    except json.JSONDecodeError:
        return []

    units: list[str] = []
    applications = payload.get("applications")
    if not isinstance(applications, dict):
        return units

    for app_data in applications.values():
        if not isinstance(app_data, dict):
            continue
        app_units = app_data.get("units")
        if not isinstance(app_units, dict):
            continue
        for unit_name in app_units.keys():
            if isinstance(unit_name, str) and unit_name:
                units.append(unit_name)

    return sorted(set(units))


def _collect_juju_for_primary(
    ssh: SSHRunner,
    machine: MachineConfig,
    artifacts_dir: Path,
) -> tuple[str, bool, str]:
    host_dir = artifacts_dir / "juju" / _sanitize(machine.hostname)
    host_dir.mkdir(parents=True, exist_ok=True)

    models = _list_models(ssh, machine)
    if not models:
        return (machine.hostname, False, "no juju models discovered")

    for model in models:
        model_dir = host_dir / _sanitize(model)
        model_dir.mkdir(parents=True, exist_ok=True)

        status = ssh.run(
            machine.ip,
            f"juju status -m {model}",
            timeout=300,
            attach_output=False,
        )
        _write_result(model_dir, "status", status.stdout, status.stderr)

        debug_log = ssh.run(
            machine.ip,
            f"juju debug-log -m {model} --replay --no-tail --lines 5000",
            timeout=900,
            attach_output=False,
        )
        _write_result(model_dir, "debug-log", debug_log.stdout, debug_log.stderr)

        units = _list_units_for_model(ssh, machine, model)
        for unit in units:
            unit_name = _sanitize(unit)
            show_unit = ssh.run(
                machine.ip,
                f"juju show-unit -m {model} {unit}",
                timeout=180,
                attach_output=False,
            )
            _write_result(
                model_dir, f"show-unit-{unit_name}", show_unit.stdout, show_unit.stderr
            )

    return (machine.hostname, True, f"models={len(models)}")


def _primary_machines(testbed: TestbedConfig) -> list[MachineConfig]:
    controls = [m for m in testbed.machines if "control" in m.roles]
    if controls:
        return controls
    return [testbed.primary_machine]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect deployment diagnostics from all testbed machines.",
    )
    parser.add_argument("--testbed-file", required=True, help="Path to testbed.yaml")
    parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Destination directory for collected artifacts (default: $ARTIFACTS_DIR or ./artifacts)",
    )
    parser.add_argument(
        "--sos-workers",
        type=int,
        default=0,
        help="Parallel workers for sos collection (default: number of testbed machines)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    testbed_path = Path(args.testbed_file).expanduser().resolve()
    if not testbed_path.is_file():
        print(f"Error: missing testbed file: {testbed_path}", file=sys.stderr)
        sys.exit(1)

    testbed = TestbedConfig.from_yaml(testbed_path)
    if testbed.ssh is None or testbed.ssh.private_key is None:
        print("Error: testbed ssh.private_key is required", file=sys.stderr)
        sys.exit(1)

    artifacts_dir = (
        Path(args.artifacts_dir or "").expanduser().resolve()
        if args.artifacts_dir
        else Path.cwd() / "artifacts"
    )
    env_artifacts = Path.cwd()
    if not args.artifacts_dir:
        from os import environ

        artifacts_var = environ.get("ARTIFACTS_DIR")
        if artifacts_var:
            env_artifacts = Path(artifacts_var).expanduser().resolve()
            artifacts_dir = env_artifacts
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    key_path = Path(testbed.ssh.private_key).expanduser().resolve()
    ssh = SSHRunner(user=testbed.ssh.user, private_key_path=key_path)

    workers = args.sos_workers if args.sos_workers > 0 else len(testbed.machines)
    workers = max(1, workers)

    logger.info(
        "Collecting sos reports from %d machines with %d workers",
        len(testbed.machines),
        workers,
    )
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _collect_sos_for_machine,
                ssh,
                machine,
                artifacts_dir,
            )
            for machine in testbed.machines
        ]
        for future in as_completed(futures):
            hostname, ok, info = future.result()
            if ok:
                logger.info("sos: %s -> %s", hostname, info)
            else:
                logger.error("sos: %s -> %s", hostname, info)
                failures.append(f"sos:{hostname}:{info}")

    primary = testbed.machines[0]
    logger.info("Collecting Juju diagnostics on primary")
    hostname, ok, info = _collect_juju_for_primary(
        ssh,
        primary,
        artifacts_dir,
    )
    if ok:
        logger.info("juju: %s -> %s", hostname, info)
    else:
        logger.error("juju: %s -> %s", hostname, info)
        failures.append(f"juju:{hostname}:{info}")

    if failures:
        logger.warning("Collection completed with failures (%d)", len(failures))
        for failure in failures:
            logger.warning("%s", failure)
        sys.exit(1)

    logger.info("Collection completed successfully: %s", artifacts_dir)
