"""Helpers for creating OpenStack SDK connections from testbed credentials."""

from __future__ import annotations

import openstack
import openstack.connection
from openstack.config.loader import OpenStackConfig


def make_connection(
    clouds_yaml_path: str,
    cloud_name: str,
) -> openstack.connection.Connection:
    """Create an SDK connection from a ``clouds.yaml`` file.

    Parameters
    ----------
    clouds_yaml_path:
        Absolute or relative path to the ``clouds.yaml`` file.
    cloud_name:
        Name of the cloud entry in the YAML file (e.g. ``"sunbeam"``).

    Returns
    -------
    openstack.connection.Connection
        A connected SDK connection ready for API calls.
    """
    config = OpenStackConfig(config_files=[clouds_yaml_path])
    cloud = config.get_one(cloud=cloud_name)
    return openstack.connection.Connection(config=cloud)
