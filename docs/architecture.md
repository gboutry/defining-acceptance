# Acceptance Test Suite -- Architecture & Philosophy

## Purpose

This test suite provides **acceptance-level validation** of a Canonical OpenStack
(Sunbeam) deployment.  It answers one question:

> _Given a concrete environment, does the cloud behave as expected?_

It is **not** a unit or integration test suite for Sunbeam itself.  It treats
Sunbeam as a black box and exercises it from the outside -- through the
`sunbeam` CLI, the OpenStack API, and SSH -- exactly the way an operator would.

## The testbed file

Every run is driven by a single `testbed.yaml` file.  The testbed is the
**single source of truth** that describes the target environment: how many
machines there are, which provider is used, what features should be enabled, and
whether the cloud is already standing or still needs to be deployed.

A copy of the file with all available options lives at `testbed.yaml.example`.

### Why a file and not CLI flags?

A Sunbeam deployment is described by dozens of interrelated parameters (provider,
topology, machine roles, OSD devices, network layout, proxy settings, ...).
Encoding all of these as individual `--flag` arguments would be unwieldy and
error-prone.  A declarative YAML file:

- is easy to version-control alongside the deployment it describes,
- can be generated programmatically by CI or by a provisioning tool,
- is self-documenting -- every field has a clear name and lives in a logical
  section.

### Key sections

| Section | Required | Purpose |
|---|---|---|
| `deployment` | yes | Provider (`manual` / `maas`), topology (`single-node` / `multi-node`), snap channel, and whether the cloud is already provisioned. |
| `machines` | yes | One entry per physical (or virtual) node.  IP, FQDN, roles, OSD devices, external network mappings. |
| `features` | no | List of Sunbeam features to enable after bootstrap (`secrets`, `caas`, `loadbalancer`, ...). |
| `network` | no | Map of external (provider) networks (`physnet → {cidr, gateway}`) and optional HTTP proxy configuration. |
| `juju` | no | Whether to use an external Juju controller (and its credentials). |
| `maas` | no | MAAS API endpoint, API key, and network-space mappings.  Only relevant when `deployment.provider` is `maas`. |
| `ssh` | no | SSH user and key paths used by the harness to connect to the machines. |

### The `provisioned` flag

Set `deployment.provisioned: true` when pointing the suite at a cloud that is
already deployed and healthy.  This skips every test tagged `@provisioning` --
no bootstrap, no join, no snap install -- and runs only the validation suites
(operations, performance, reliability, security).

This is the typical mode for nightly regression runs against a long-lived
environment, or for quickly validating a specific concern without waiting for a
full re-deploy.

## Test suite organisation

Tests are split into five suites, each in its own directory under `features/`
(Gherkin) and `tests/step_defs/` (Python):

| Suite | Tag | Scope |
|---|---|---|
| **Provisioning** | `@provisioning` | Deploying the cloud from scratch.  Mode-specific -- scenarios carry additional markers like `@single-node`, `@maas`, `@external-juju`. |
| **Operations** | `@operations` | Day-2 actions: enabling features, running Tempest validation.  Not tied to a specific deployment mode. |
| **Performance** | `@performance` | Throughput and latency benchmarks (network, storage, ...).  Not tied to a specific deployment mode. |
| **Reliability** | `@reliability` | Failure scenarios, upgrade paths, availability guarantees.  Not tied to a specific deployment mode. |
| **Security** | `@security` | Encryption in transit, access control, network isolation, compliance.  Not tied to a specific deployment mode. |

Only provisioning is deployment-mode-specific.  The other four suites are
written to be **generic**: they assume a working cloud exists and validate its
behaviour regardless of how it was deployed.

## Marker-driven test selection

Tests declare their requirements through Gherkin tags (`@maas`,
`@three-node`, `@secrets`, ...).  At collection time, the framework reads the
testbed file and **automatically skips** every test whose requirements are not
satisfied by the environment.

There is no `if/skip` logic inside step definitions.  The mapping lives in a
single place -- the `pytest_collection_modifyitems` hook in `tests/conftest.py`
-- and works as follows:

| Marker | Test runs when... |
|---|---|
| `@single-node` | `deployment.topology` is `single-node` |
| `@multi-node` | `deployment.topology` is `multi-node` |
| `@maas` | `deployment.provider` is `maas` |
| `@external-juju` | `juju.external` is `true` |
| `@proxy` | `network.proxy.enabled` is `true` |
| `@three-node` | 3 or more machines are listed |
| `@provisioning` | `deployment.provisioned` is `false` (default) |
| `@secrets` | `secrets` is in the `features` list |
| `@caas` | `caas` is in the `features` list |
| `@loadbalancer` | `loadbalancer` is in the `features` list |

Markers are composable.  A scenario tagged `@maas @three-node` only runs
against a MAAS deployment with at least three machines.

A test with **no** deployment/feature marker runs against every testbed.

### Running a subset manually

The marker system also works with pytest's `-m` flag:

```bash
# Only provisioning
pytest tests/ -m provisioning

# Everything except provisioning
pytest tests/ -m "not provisioning"

# Reliability + security
pytest tests/ -m "reliability or security"
```

Combined with the automatic skip, this means you can always run `pytest tests/`
without fear of irrelevant tests failing -- they will be cleanly skipped.

## Writing a new test

1. **Pick the right suite.**  If the test validates deployment steps, it goes in
   `provisioning`.  Everything else goes in the suite that matches its concern.

2. **Write the Gherkin scenario** in `features/<suite>/<topic>.feature`.  Tag it
   with the suite marker and any capability markers it needs:

   ```gherkin
   @reliability @three-node
   Scenario: Storage survives single OSD host failure
     Given a VM with an attached volume
     When one OSD host is powered off
     Then the volume remains accessible from the VM
   ```

3. **Implement step definitions** in `tests/step_defs/<suite>/`.  Shared steps
   (like "the cloud is provisioned") live in `conftest.py` files at the
   appropriate level -- do not duplicate them.

4. **Register new markers** in `pyproject.toml` under `[tool.pytest] markers` if
   you introduce a tag that does not exist yet.  The suite uses
   `--strict-markers`, so undeclared markers will cause collection to fail.

## Mock mode

Set the environment variable `MOCK_MODE=1` to run the entire suite without any
real infrastructure.  SSH calls return canned responses, fixtures return
synthetic data.  This is useful for:

- developing and debugging step definitions locally,
- validating that the Gherkin/step wiring is correct,
- running the suite in CI to catch syntax or import errors.

## Diagram

```
                      testbed.yaml
                          |
                          v
                   ┌──────────────┐
                   │ TestbedConfig │  (parsed at collection time)
                   └──────┬───────┘
                          |
             ┌────────────┴────────────┐
             v                         v
    pytest_collection            Session fixtures
    _modifyitems                 (bootstrapped_cloud,
    (auto-skip based              configured_cloud,
     on markers)                  running_vm, ...)
                                       |
            ┌──────────┬───────────┬───┴──────┬────────────┐
            v          v           v          v            v
      provisioning operations performance reliability  security
      (@single-node  (generic)  (generic)  (generic)   (generic)
       @maas ...)
```
