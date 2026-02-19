# Canonical OpenStack Acceptance Tests

Black-box validation of a [Canonical OpenStack](https://ubuntu.com/openstack) (Sunbeam)
deployment. It exercises the cloud from the outside — through the `sunbeam` CLI, the
OpenStack API, and SSH — exactly as an operator would.

## Goals

- **Catch regressions** before they reach production by running the full suite against
  every snap revision in CI.
- **Gate deployments** by verifying that a freshly provisioned cloud meets acceptance
  criteria before being handed over.
- **Cover the whole lifecycle**: from bare-metal provisioning to day-2 operations,
  performance benchmarks, reliability under failure, and security posture.

## The testbed file

Every run is driven by a `testbed.yaml` that describes the target environment.
Copy the example and fill it in:

```bash
cp testbed.yaml.example testbed.yaml
```

Key sections:

| Section | Purpose |
|---|---|
| `deployment` | Provider (`manual`/`maas`), topology, snap channel. Set `provisioned: true` to skip deployment tests on an already-running cloud. |
| `machines` | One entry per node — IP, roles (`control`/`compute`/`storage`), OSD devices, network interfaces. |
| `features` | Sunbeam features to enable after bootstrap (`secrets`, `loadbalancer`, `caas`). |
| `ssh` | User and private key path used by the harness. |
| `juju` | Set `external: true` to reuse an existing Juju controller. |
| `maas` | MAAS API endpoint and credentials (only for `provider: maas`). |

## Running tests

### Prerequisites

```bash
pip install -e .
```

Place your SSH private key at `./ssh_private_key` (or set `ssh.private_key` in
`testbed.yaml`), then point the suite at your environment:

```bash
pytest tests/ --testbed-file testbed.yaml
```

### Select a subset

```bash
# Functional suite only (provisioning + day-2 ops)
pytest tests/ -m functional

# Everything except deployment steps (assumes cloud is already up)
pytest tests/ -m "not provisioning"

# Reliability and security on a running cloud
pytest tests/ -m "reliability or security"
```

The framework reads `testbed.yaml` at collection time and **automatically skips** any
test whose requirements the environment does not satisfy — so `pytest tests/` is always
safe to run in full.

### Mock mode

Run the entire suite without real infrastructure to validate wiring and imports:

```bash
MOCK_MODE=1 pytest tests/
```

## Reporting

### Test Observer

Set `TO_URL` and `TO_SNAP_REVISION` to stream results to a
[Test Observer](https://github.com/canonical/test_observer) instance in real time.
One test execution is created per suite category.  Step-level events are posted
as the test runs, giving a live timeline in the UI.

```bash
export TO_URL=https://test-observer-api.example.com
export TO_SNAP_REVISION=12345
pytest tests/
```

Optional variables: `TO_SNAP_NAME`, `TO_SNAP_TRACK`, `TO_SNAP_STAGE`,
`TO_SNAP_VERSION`, `TO_SNAP_STORE`, `TO_ENVIRONMENT`, `TO_TEST_PLAN`,
`TO_ARCH`, `TO_CI_LINK`.

### Deferred upload

For runs without direct access to Test Observer (e.g. air-gapped lab), record
results locally and upload later:

```bash
# Record to a local directory during the run
TO_URL=file:///tmp/to-results TO_SNAP_REVISION=12345 pytest tests/

# Upload when connectivity is available
to-upload /tmp/to-results --to-url https://test-observer-api.example.com
```
