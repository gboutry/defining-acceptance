from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class DeploymentConfig:
    provider: str
    topology: str
    channel: str
    manifest: Optional[str] = None
    provisioned: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> DeploymentConfig:
        provider = data.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("deployment.provider must be a non-empty string")

        topology = data.get("topology")
        if not isinstance(topology, str) or not topology.strip():
            raise ValueError("deployment.topology must be a non-empty string")

        channel = data.get("channel")
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("deployment.channel must be a non-empty string")

        manifest = data.get("manifest")
        if manifest is not None and not isinstance(manifest, str):
            raise ValueError("deployment.manifest must be a string when set")

        provisioned = data.get("provisioned", False)
        if not isinstance(provisioned, bool):
            raise ValueError("deployment.provisioned must be a boolean")

        return cls(
            provider=provider,
            topology=topology,
            channel=channel,
            manifest=manifest,
            provisioned=provisioned,
        )


@dataclass(frozen=True)
class JujuControllerConfig:
    name: str
    endpoint: str
    user: str
    password: str

    @classmethod
    def from_dict(cls, data: dict) -> JujuControllerConfig:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("juju.controller.name must be a non-empty string")

        endpoint = data.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("juju.controller.endpoint must be a non-empty string")

        user = data.get("user")
        if not isinstance(user, str) or not user.strip():
            raise ValueError("juju.controller.user must be a non-empty string")

        password = data.get("password")
        if not isinstance(password, str):
            raise ValueError("juju.controller.password must be a string")

        return cls(name=name, endpoint=endpoint, user=user, password=password)


@dataclass(frozen=True)
class JujuConfig:
    external: bool = False
    controller: Optional[JujuControllerConfig] = None

    @classmethod
    def from_dict(cls, data: dict) -> JujuConfig:
        external = data.get("external", False)
        if not isinstance(external, bool):
            raise ValueError("juju.external must be a boolean")

        controller_raw = data.get("controller")
        controller = None
        if controller_raw is not None:
            if not isinstance(controller_raw, dict):
                raise ValueError("juju.controller must be a mapping")
            controller = JujuControllerConfig.from_dict(controller_raw)

        return cls(external=external, controller=controller)


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool = False
    http: Optional[str] = None
    https: Optional[str] = None
    no_proxy: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> ProxyConfig:
        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("network.proxy.enabled must be a boolean")

        http = data.get("http")
        if http is not None and not isinstance(http, str):
            raise ValueError("network.proxy.http must be a string when set")

        https = data.get("https")
        if https is not None and not isinstance(https, str):
            raise ValueError("network.proxy.https must be a string when set")

        no_proxy = data.get("no_proxy")
        if no_proxy is not None and not isinstance(no_proxy, str):
            raise ValueError("network.proxy.no_proxy must be a string when set")

        return cls(enabled=enabled, http=http, https=https, no_proxy=no_proxy)


@dataclass(frozen=True)
class ExternalNetworkConfig:
    cidr: str
    gateway: str

    @classmethod
    def from_dict(cls, physnet: str, data: dict) -> ExternalNetworkConfig:
        cidr = data.get("cidr")
        if not isinstance(cidr, str) or not cidr.strip():
            raise ValueError(f"network.external.{physnet}.cidr must be a non-empty string")

        gateway = data.get("gateway")
        if not isinstance(gateway, str) or not gateway.strip():
            raise ValueError(f"network.external.{physnet}.gateway must be a non-empty string")

        return cls(cidr=cidr, gateway=gateway)


@dataclass(frozen=True)
class NetworkConfig:
    proxy: Optional[ProxyConfig] = None
    external: dict[str, ExternalNetworkConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> NetworkConfig:
        proxy_raw = data.get("proxy")
        proxy = None
        if proxy_raw is not None:
            if not isinstance(proxy_raw, dict):
                raise ValueError("network.proxy must be a mapping")
            proxy = ProxyConfig.from_dict(proxy_raw)

        external_raw = data.get("external", {})
        if not isinstance(external_raw, dict):
            raise ValueError("network.external must be a mapping of physnet names to {cidr, gateway}")
        external: dict[str, ExternalNetworkConfig] = {}
        for physnet, net_data in external_raw.items():
            if not isinstance(net_data, dict):
                raise ValueError(f"network.external.{physnet} must be a mapping")
            external[physnet] = ExternalNetworkConfig.from_dict(physnet, net_data)

        return cls(proxy=proxy, external=external)


@dataclass(frozen=True)
class ExternalNetworks:
    external: str

    @classmethod
    def from_dict(cls, data: dict) -> ExternalNetworks:
        external = data.get("external")
        if not isinstance(external, str) or not external.strip():
            raise ValueError(
                "Machine external_networks.external must be a non-empty string"
            )
        return cls(external=external)


@dataclass(frozen=True)
class MachineConfig:
    hostname: str
    ip: str
    roles: list[str]
    fqdn: Optional[str] = None
    osd_devices: list[str] = field(default_factory=list)
    external_networks: Optional[ExternalNetworks] = None

    @classmethod
    def from_dict(cls, data: dict) -> MachineConfig:
        hostname = data.get("hostname")
        if not isinstance(hostname, str) or not hostname.strip():
            raise ValueError("Machine hostname must be a non-empty string")

        ip = data.get("ip")
        if not isinstance(ip, str) or not ip.strip():
            raise ValueError(f"Machine '{hostname}' must include a non-empty ip")

        fqdn = data.get("fqdn")
        if fqdn is not None and (not isinstance(fqdn, str) or not fqdn.strip()):
            raise ValueError(
                f"Machine '{hostname}' fqdn must be a non-empty string when set"
            )

        roles_raw = data.get("roles", [])
        if not isinstance(roles_raw, list):
            raise ValueError(f"Machine '{hostname}' roles must be a list")
        for item in roles_raw:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"Machine '{hostname}' roles must be a list of non-empty strings"
                )
        roles: list[str] = list(roles_raw)

        osd_devices_raw = data.get("osd_devices", data.get("osd-devices", []))
        if isinstance(osd_devices_raw, str):
            osd_devices: list[str] = (
                [osd_devices_raw] if osd_devices_raw.strip() else []
            )
        elif isinstance(osd_devices_raw, list):
            for item in osd_devices_raw:
                if not isinstance(item, str):
                    raise ValueError(
                        f"Machine '{hostname}' osd_devices must be a list of strings"
                    )
            osd_devices = list(osd_devices_raw)
        else:
            raise ValueError(
                f"Machine '{hostname}' osd_devices must be a list of strings"
            )

        external_networks_raw = data.get(
            "external_networks", data.get("external-networks")
        )
        external_networks = None
        if external_networks_raw is not None:
            if not isinstance(external_networks_raw, dict):
                raise ValueError(
                    f"Machine '{hostname}' external_networks must be a mapping"
                )
            external_networks = ExternalNetworks.from_dict(external_networks_raw)

        return cls(
            hostname=hostname,
            ip=ip,
            roles=roles,
            fqdn=fqdn,
            osd_devices=osd_devices,
            external_networks=external_networks,
        )


@dataclass(frozen=True)
class MaasNetworkSpaces:
    management: Optional[str] = None
    storage: Optional[str] = None
    internal: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> MaasNetworkSpaces:
        management = data.get("management")
        if management is not None and not isinstance(management, str):
            raise ValueError("maas.network_spaces.management must be a string when set")

        storage = data.get("storage")
        if storage is not None and not isinstance(storage, str):
            raise ValueError("maas.network_spaces.storage must be a string when set")

        internal = data.get("internal")
        if internal is not None and not isinstance(internal, str):
            raise ValueError("maas.network_spaces.internal must be a string when set")

        return cls(management=management, storage=storage, internal=internal)


@dataclass(frozen=True)
class MaasConfig:
    endpoint: str
    api_key: str
    network_spaces: Optional[MaasNetworkSpaces] = None

    @classmethod
    def from_dict(cls, data: dict) -> MaasConfig:
        endpoint = data.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("maas.endpoint must be a non-empty string")

        api_key = data.get("api_key", data.get("api-key"))
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("maas.api_key must be a non-empty string")

        network_spaces_raw = data.get("network_spaces", data.get("network-spaces"))
        network_spaces = None
        if network_spaces_raw is not None:
            if not isinstance(network_spaces_raw, dict):
                raise ValueError("maas.network_spaces must be a mapping")
            network_spaces = MaasNetworkSpaces.from_dict(network_spaces_raw)

        return cls(endpoint=endpoint, api_key=api_key, network_spaces=network_spaces)


@dataclass(frozen=True)
class SshConfig:
    user: str
    private_key: Optional[str] = None
    public_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> SshConfig:
        user = data.get("user")
        if not isinstance(user, str) or not user.strip():
            raise ValueError("ssh.user must be a non-empty string")

        private_key = data.get("private_key", data.get("private-key"))
        if private_key is not None and not isinstance(private_key, str):
            raise ValueError("ssh.private_key must be a string when set")

        public_key = data.get("public_key", data.get("public-key"))
        if public_key is not None and not isinstance(public_key, str):
            raise ValueError("ssh.public_key must be a string when set")

        return cls(user=user, private_key=private_key, public_key=public_key)


@dataclass(frozen=True)
class TestbedConfig:
    machines: list[MachineConfig]
    deployment: Optional[DeploymentConfig] = None
    juju: Optional[JujuConfig] = None
    network: Optional[NetworkConfig] = None
    features: list[str] = field(default_factory=list)
    maas: Optional[MaasConfig] = None
    ssh: Optional[SshConfig] = None

    @property
    def primary_machine(self) -> MachineConfig:
        for machine in self.machines:
            if "control" in machine.roles:
                return machine
        return self.machines[0]

    @property
    def is_multi_node(self) -> bool:
        return len(self.machines) > 1

    @property
    def is_single_node(self) -> bool:
        return len(self.machines) == 1

    @property
    def is_maas(self) -> bool:
        return self.deployment is not None and self.deployment.provider == "maas"

    def has_feature(self, name: str) -> bool:
        return name in self.features

    @property
    def has_proxy(self) -> bool:
        return (
            self.network is not None
            and self.network.proxy is not None
            and self.network.proxy.enabled
        )

    @property
    def has_external_juju(self) -> bool:
        return self.juju is not None and self.juju.external

    @property
    def is_provisioned(self) -> bool:
        return self.deployment is not None and self.deployment.provisioned

    @classmethod
    def from_dict(cls, data: dict) -> TestbedConfig:
        machines_raw = data.get("machines")
        if not isinstance(machines_raw, list) or not machines_raw:
            raise ValueError("Testbed must contain a non-empty machines list")

        machines: list[MachineConfig] = []
        for item in machines_raw:
            if not isinstance(item, dict):
                raise ValueError("Each machine entry in testbed must be a mapping")
            machines.append(MachineConfig.from_dict(item))

        deployment_raw = data.get("deployment")
        deployment = None
        if deployment_raw is not None:
            if not isinstance(deployment_raw, dict):
                raise ValueError("deployment must be a mapping")
            deployment = DeploymentConfig.from_dict(deployment_raw)

        juju_raw = data.get("juju")
        juju = None
        if juju_raw is not None:
            if not isinstance(juju_raw, dict):
                raise ValueError("juju must be a mapping")
            juju = JujuConfig.from_dict(juju_raw)

        network_raw = data.get("network")
        network = None
        if network_raw is not None:
            if not isinstance(network_raw, dict):
                raise ValueError("network must be a mapping")
            network = NetworkConfig.from_dict(network_raw)

        features_raw = data.get("features", [])
        if not isinstance(features_raw, list):
            raise ValueError("features must be a list")
        for item in features_raw:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Each feature entry must be a non-empty string")
        features: list[str] = list(features_raw)

        maas_raw = data.get("maas")
        maas = None
        if maas_raw is not None:
            if not isinstance(maas_raw, dict):
                raise ValueError("maas must be a mapping")
            maas = MaasConfig.from_dict(maas_raw)

        ssh_raw = data.get("ssh")
        ssh = None
        if ssh_raw is not None:
            if not isinstance(ssh_raw, dict):
                raise ValueError("ssh must be a mapping")
            ssh = SshConfig.from_dict(ssh_raw)

        return cls(
            machines=machines,
            deployment=deployment,
            juju=juju,
            network=network,
            features=features,
            maas=maas,
            ssh=ssh,
        )

    @classmethod
    def from_yaml(cls, path: Path) -> TestbedConfig:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(
                f"Testbed YAML file '{path}' must contain a mapping at the top level"
            )
        return cls.from_dict(data)
