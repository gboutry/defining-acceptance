Feature: Network Resilience
  As a cloud operator
  I want to verify network connectivity and DNS resolution
  So that I can ensure reliable network communication

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a VM is running

  @reliability
  Scenario: Network ACLs enforced
    Given the VM has restricted network access
    When I attempt to connect to a blocked IP
    Then the connection should be refused or timeout

  @reliability
  Scenario: DNS resolution works
    When I resolve external hostnames
    Then DNS resolution should succeed

  @reliability
  Scenario: Internal network communication
    Given multiple VMs are running on the same network
    When the VMs communicate with each other
    Then the communication should succeed
