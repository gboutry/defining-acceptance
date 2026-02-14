Feature: Network Isolation
  As a cloud operator
  I want to verify network isolation between VMs and networks
  So that I can ensure proper security boundaries are enforced

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a VM is running

  @security
  Scenario: Restricted network cannot reach external IPs
    Given the VM is on the restricted network
    When I attempt to ping an external IP
    Then the connection should be blocked

  @security
  Scenario: Proxy filtering works
    Given the VM is configured to use a proxy
    When I make a web request
    Then the request should go through the proxy
