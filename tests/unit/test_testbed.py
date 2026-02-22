from __future__ import annotations

import pytest

from defining_acceptance.testbed import (
    DeploymentConfig,
    MachineConfig,
    SshConfig,
    TestbedConfig,
)

VALID_MACHINE = {"hostname": "node1", "ip": "10.0.0.1"}


# ---------------------------------------------------------------------------
# DeploymentConfig.from_dict
# ---------------------------------------------------------------------------


class TestDeploymentConfigFromDict:
    def test_valid_channel_only(self) -> None:
        """Valid config with channel only is accepted."""
        cfg = DeploymentConfig.from_dict(
            {"provider": "lxd", "topology": "single", "channel": "2024.1/stable"}
        )
        assert cfg.channel == "2024.1/stable"
        assert cfg.revision is None

    def test_valid_revision_only(self) -> None:
        """Valid config with revision only is accepted."""
        cfg = DeploymentConfig.from_dict(
            {"provider": "lxd", "topology": "single", "revision": 42}
        )
        assert cfg.revision == 42
        assert cfg.channel is None

    def test_valid_channel_and_revision(self) -> None:
        """Valid config with both channel and revision is accepted."""
        cfg = DeploymentConfig.from_dict(
            {
                "provider": "lxd",
                "topology": "single",
                "channel": "2024.1/stable",
                "revision": 42,
            }
        )
        assert cfg.channel == "2024.1/stable"
        assert cfg.revision == 42

    def test_missing_provider_raises(self) -> None:
        """Missing provider raises ValueError."""
        with pytest.raises(ValueError, match=r"provider"):
            DeploymentConfig.from_dict(
                {"topology": "single", "channel": "2024.1/stable"}
            )

    def test_empty_provider_raises(self) -> None:
        """Empty provider string raises ValueError."""
        with pytest.raises(ValueError, match=r"provider"):
            DeploymentConfig.from_dict(
                {"provider": "", "topology": "single", "channel": "2024.1/stable"}
            )

    def test_missing_topology_raises(self) -> None:
        """Missing topology raises ValueError."""
        with pytest.raises(ValueError, match=r"topology"):
            DeploymentConfig.from_dict({"provider": "lxd", "channel": "2024.1/stable"})

    def test_empty_topology_raises(self) -> None:
        """Empty topology string raises ValueError."""
        with pytest.raises(ValueError, match=r"topology"):
            DeploymentConfig.from_dict(
                {"provider": "lxd", "topology": "", "channel": "2024.1/stable"}
            )

    def test_empty_channel_raises(self) -> None:
        """Providing an empty string for channel raises ValueError."""
        with pytest.raises(ValueError, match=r"channel"):
            DeploymentConfig.from_dict(
                {"provider": "lxd", "topology": "single", "channel": ""}
            )

    def test_non_int_revision_raises(self) -> None:
        """Non-integer revision raises ValueError."""
        with pytest.raises(ValueError, match=r"revision"):
            DeploymentConfig.from_dict(
                {"provider": "lxd", "topology": "single", "revision": "latest"}
            )

    def test_neither_channel_nor_revision_raises(self) -> None:
        """Omitting both channel and revision raises ValueError."""
        with pytest.raises(ValueError, match=r"channel.*revision|revision.*channel"):
            DeploymentConfig.from_dict({"provider": "lxd", "topology": "single"})


# ---------------------------------------------------------------------------
# MachineConfig.from_dict
# ---------------------------------------------------------------------------


class TestMachineConfigFromDict:
    def test_valid_minimal(self) -> None:
        """Valid minimal dict (hostname + ip) is accepted."""
        cfg = MachineConfig.from_dict(VALID_MACHINE)
        assert cfg.hostname == "node1"
        assert cfg.ip == "10.0.0.1"
        assert cfg.fqdn is None
        assert cfg.osd_devices == []
        assert cfg.external_networks == {}

    def test_missing_hostname_raises(self) -> None:
        """Missing hostname raises ValueError."""
        with pytest.raises(ValueError, match=r"hostname"):
            MachineConfig.from_dict({"ip": "10.0.0.1"})

    def test_missing_ip_raises(self) -> None:
        """Missing ip raises ValueError."""
        with pytest.raises(ValueError, match=r"ip"):
            MachineConfig.from_dict({"hostname": "node1"})

    def test_optional_fqdn_accepted(self) -> None:
        """fqdn is accepted when provided as a non-empty string."""
        cfg = MachineConfig.from_dict(
            {"hostname": "node1", "ip": "10.0.0.1", "fqdn": "node1.example.com"}
        )
        assert cfg.fqdn == "node1.example.com"

    def test_empty_fqdn_raises(self) -> None:
        """Empty fqdn string raises ValueError."""
        with pytest.raises(ValueError, match=r"fqdn"):
            MachineConfig.from_dict({"hostname": "node1", "ip": "10.0.0.1", "fqdn": ""})

    def test_osd_devices_single_string(self) -> None:
        """A single osd_devices string becomes a one-element list."""
        cfg = MachineConfig.from_dict(
            {"hostname": "node1", "ip": "10.0.0.1", "osd_devices": "/dev/sdb"}
        )
        assert cfg.osd_devices == ["/dev/sdb"]

    def test_osd_devices_empty_string(self) -> None:
        """An empty osd_devices string produces an empty list."""
        cfg = MachineConfig.from_dict(
            {"hostname": "node1", "ip": "10.0.0.1", "osd_devices": ""}
        )
        assert cfg.osd_devices == []

    def test_osd_devices_list(self) -> None:
        """A list value for osd_devices is preserved."""
        cfg = MachineConfig.from_dict(
            {
                "hostname": "node1",
                "ip": "10.0.0.1",
                "osd_devices": ["/dev/sdb", "/dev/sdc"],
            }
        )
        assert cfg.osd_devices == ["/dev/sdb", "/dev/sdc"]

    def test_osd_devices_kebab_key(self) -> None:
        """'osd-devices' (kebab) is accepted as an alias for 'osd_devices'."""
        cfg = MachineConfig.from_dict(
            {"hostname": "node1", "ip": "10.0.0.1", "osd-devices": "/dev/sdb"}
        )
        assert cfg.osd_devices == ["/dev/sdb"]

    def test_external_networks_parsed(self) -> None:
        """external_networks dict is parsed correctly."""
        cfg = MachineConfig.from_dict(
            {
                "hostname": "node1",
                "ip": "10.0.0.1",
                "external_networks": {"physnet1": "eth1"},
            }
        )
        assert cfg.external_networks == {"physnet1": "eth1"}

    def test_external_networks_kebab_key(self) -> None:
        """'external-networks' (kebab) is accepted as an alias."""
        cfg = MachineConfig.from_dict(
            {
                "hostname": "node1",
                "ip": "10.0.0.1",
                "external-networks": {"physnet1": "eth1"},
            }
        )
        assert cfg.external_networks == {"physnet1": "eth1"}


# ---------------------------------------------------------------------------
# SshConfig.from_dict
# ---------------------------------------------------------------------------


class TestSshConfigFromDict:
    def test_valid_user_only(self) -> None:
        """Valid config with only user is accepted."""
        cfg = SshConfig.from_dict({"user": "ubuntu"})
        assert cfg.user == "ubuntu"
        assert cfg.private_key is None
        assert cfg.proxy_jump is None

    def test_missing_user_raises(self) -> None:
        """Missing user raises ValueError."""
        with pytest.raises(ValueError, match=r"user"):
            SshConfig.from_dict({})

    def test_private_key_kebab_key(self) -> None:
        """'private-key' (kebab) is accepted as an alias for 'private_key'."""
        cfg = SshConfig.from_dict({"user": "ubuntu", "private-key": "/path/to/key"})
        assert cfg.private_key == "/path/to/key"

    def test_proxy_jump_kebab_key(self) -> None:
        """'proxy-jump' (kebab) is accepted as an alias for 'proxy_jump'."""
        cfg = SshConfig.from_dict(
            {"user": "ubuntu", "proxy-jump": "bastion.example.com"}
        )
        assert cfg.proxy_jump == "bastion.example.com"


# ---------------------------------------------------------------------------
# TestbedConfig.from_dict
# ---------------------------------------------------------------------------


class TestTestbedConfigFromDict:
    def test_valid_minimal(self) -> None:
        """A minimal testbed dict with one machine is accepted."""
        cfg = TestbedConfig.from_dict({"machines": [VALID_MACHINE]})
        assert len(cfg.machines) == 1
        assert cfg.machines[0].hostname == "node1"

    def test_empty_machines_raises(self) -> None:
        """An empty machines list raises ValueError."""
        with pytest.raises(ValueError, match=r"machines"):
            TestbedConfig.from_dict({"machines": []})

    def test_machines_not_list_raises(self) -> None:
        """machines that is not a list raises ValueError."""
        with pytest.raises(ValueError, match=r"machines"):
            TestbedConfig.from_dict({"machines": "node1"})

    def test_optional_deployment_parsed(self) -> None:
        """deployment sub-config is parsed when present."""
        cfg = TestbedConfig.from_dict(
            {
                "machines": [VALID_MACHINE],
                "deployment": {
                    "provider": "lxd",
                    "topology": "single",
                    "channel": "2024.1/stable",
                },
            }
        )
        assert cfg.deployment is not None
        assert cfg.deployment.provider == "lxd"

    def test_optional_ssh_parsed(self) -> None:
        """ssh sub-config is parsed when present."""
        cfg = TestbedConfig.from_dict(
            {"machines": [VALID_MACHINE], "ssh": {"user": "ubuntu"}}
        )
        assert cfg.ssh is not None
        assert cfg.ssh.user == "ubuntu"

    def test_features_list_parsed(self) -> None:
        """features list is parsed and stored correctly."""
        cfg = TestbedConfig.from_dict(
            {"machines": [VALID_MACHINE], "features": ["ceph", "ovn"]}
        )
        assert cfg.features == ["ceph", "ovn"]


# ---------------------------------------------------------------------------
# TestbedConfig properties
# ---------------------------------------------------------------------------

CONTROL_MACHINE = {"hostname": "ctrl", "ip": "10.0.0.2", "roles": ["control"]}
WORKER_MACHINE = {"hostname": "worker", "ip": "10.0.0.3"}


class TestTestbedConfigProperties:
    def test_primary_machine_control_role(self) -> None:
        """primary_machine returns the machine with 'control' role."""
        cfg = TestbedConfig.from_dict(
            {"machines": [VALID_MACHINE, CONTROL_MACHINE, WORKER_MACHINE]}
        )
        assert cfg.primary_machine.hostname == "ctrl"

    def test_primary_machine_fallback_to_first(self) -> None:
        """primary_machine falls back to machines[0] when no control role present."""
        cfg = TestbedConfig.from_dict({"machines": [VALID_MACHINE, WORKER_MACHINE]})
        assert cfg.primary_machine.hostname == "node1"

    def test_is_multi_node_true(self) -> None:
        """is_multi_node is True when there are 2 or more machines."""
        cfg = TestbedConfig.from_dict({"machines": [VALID_MACHINE, WORKER_MACHINE]})
        assert cfg.is_multi_node is True

    def test_is_single_node_true(self) -> None:
        """is_single_node is True when there is exactly 1 machine."""
        cfg = TestbedConfig.from_dict({"machines": [VALID_MACHINE]})
        assert cfg.is_single_node is True

    def test_is_maas_true(self) -> None:
        """is_maas is True when deployment.provider is 'maas'."""
        cfg = TestbedConfig.from_dict(
            {
                "machines": [VALID_MACHINE],
                "deployment": {
                    "provider": "maas",
                    "topology": "multi",
                    "channel": "2024.1/stable",
                },
            }
        )
        assert cfg.is_maas is True

    def test_is_maas_false_without_deployment(self) -> None:
        """is_maas is False when no deployment is configured."""
        cfg = TestbedConfig.from_dict({"machines": [VALID_MACHINE]})
        assert cfg.is_maas is False

    def test_has_feature_present(self) -> None:
        """has_feature returns True when the feature is in the list."""
        cfg = TestbedConfig.from_dict(
            {"machines": [VALID_MACHINE], "features": ["ceph"]}
        )
        assert cfg.has_feature("ceph") is True

    def test_has_feature_absent(self) -> None:
        """has_feature returns False when the feature is not present."""
        cfg = TestbedConfig.from_dict({"machines": [VALID_MACHINE]})
        assert cfg.has_feature("ceph") is False

    def test_has_proxy_true(self) -> None:
        """has_proxy is True when network.proxy.enabled is True."""
        cfg = TestbedConfig.from_dict(
            {
                "machines": [VALID_MACHINE],
                "network": {"proxy": {"enabled": True}},
            }
        )
        assert cfg.has_proxy is True

    def test_has_external_juju_true(self) -> None:
        """has_external_juju is True when juju.external is True."""
        cfg = TestbedConfig.from_dict(
            {"machines": [VALID_MACHINE], "juju": {"external": True}}
        )
        assert cfg.has_external_juju is True

    def test_is_provisioned_true(self) -> None:
        """is_provisioned is True when deployment.provisioned is True."""
        cfg = TestbedConfig.from_dict(
            {
                "machines": [VALID_MACHINE],
                "deployment": {
                    "provider": "lxd",
                    "topology": "single",
                    "channel": "2024.1/stable",
                    "provisioned": True,
                },
            }
        )
        assert cfg.is_provisioned is True
