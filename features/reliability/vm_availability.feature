Feature: VM Availability
  As a cloud operator
  I want to verify VMs start successfully and remain running
  So that I can ensure service availability and stability

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a VM is running

  @reliability
  Scenario: VM starts successfully
    When I check the status of all VMs
    Then all VMs should be in running state
    And all VMs should be reachable via SSH

  @reliability
  Scenario: VM remains running for extended period
    When I wait for 60 seconds
    Then the VM should still be running
    And the VM should still be reachable via SSH

  @reliability
  Scenario: VM recovers from restart
    When I restart the VM
    Then the VM should come back up within 300 seconds
    And the VM should be reachable via SSH after restart
