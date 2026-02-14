Feature: Network Throughput
  As a cloud operator
  I want to measure network performance between VMs
  So that I can validate network infrastructure meets requirements

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a VM is running

  @performance
  Scenario: Internal network throughput on same host
    Given a second VM on the same network and host
    When I measure throughput between the VMs
    Then throughput should be at least 1 Gbps

  @performance
  Scenario: Internal network throughput on different host
    Given a second VM on the same network but different host
    When I measure throughput between the VMs
    Then throughput should be at least 1 Gbps

  @performance
  Scenario: External network throughput
    When I download data from an external source
    Then download speed should be acceptable
