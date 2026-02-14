Feature: Deploy with MAAS
  As an operator
  I want to deploy Canonical OpenStack using MAAS as the bare metal provider
  So that I can leverage MAAS for hardware provisioning

  Background:
    Given a working MAAS environment exists
    And the machines are commissioned and ready in MAAS

  @provisioning
  @maas
  Scenario: Add MAAS provider to Sunbeam
    Given I have a MAAS region API token
    When I add the MAAS provider to Sunbeam
    Then the MAAS provider should be registered

  @provisioning
  @maas
  Scenario: Map network spaces
    Given the MAAS provider is configured
    When I map network spaces to cloud networks
    Then the network mappings should be configured

  @provisioning
  @maas
  Scenario: Bootstrap cloud with MAAS
    Given the MAAS provider is configured
    And network spaces are mapped
    When I bootstrap the orchestration layer
    Then the Juju controller should be deployed
    When I deploy the cloud
    Then all control plane services should be running
