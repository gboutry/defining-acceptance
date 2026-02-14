Feature: Data Encryption
  As a cloud operator
  I want to verify data is encrypted in transit
  So that I can ensure data confidentiality and integrity

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage
    And a VM is running

  @security
  Scenario: Internal network traffic is encrypted
    Given a second VM is running on the internal network
    When I check network traffic between the VMs
    Then traffic should be encrypted

  @security
  Scenario: External connections use TLS
    When I connect to an external service
    Then TLS should be enforced
