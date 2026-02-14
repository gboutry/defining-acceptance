Feature: Storage Availability
  As a cloud operator
  I want to verify storage remains available during failures
  So that I can ensure data storage is resilient and fault-tolerant

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a 3-node deployment exists

  @reliability
  @three-node
  Scenario: VM with volume can be spawned
    When I spawn a VM with a volume attached
    Then the VM should be running
    And the volume should be accessible

  @reliability
  @three-node
  Scenario: Storage remains available when one OSD host fails
    Given a VM with a volume attached
    When I stop the OSD daemons on one host
    Then storage should remain available
    And I should be able to read from the volume
    And I should be able to write to the volume
