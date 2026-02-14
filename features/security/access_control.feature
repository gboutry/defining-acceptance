Feature: Access Control
  As a cloud operator
  I want to verify SSH access controls
  So that I can ensure only authorized users can access VMs

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a VM is running

  @security
  Scenario: SSH with correct key succeeds
    When I connect with the correct SSH key
    Then the connection should succeed

  @security
  Scenario: SSH without key fails
    When I connect without an SSH key
    Then the connection should be refused
