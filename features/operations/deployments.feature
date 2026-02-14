Feature: OpenStack Service Deployments
  As a cloud operator
  I want my deployment tool to correctly configure OpenStack services
  So that they pass native integration tests

  Background:
    Given the cloud is provisioned
    And the cloud is configured for sample usage

  @operations
  Scenario Outline: Features are deployed correctly
    Given the feature "<feature>" is enabled
    When I run Tempest tests for the feature
    Then the Tempest run should pass successfully

    Examples:
      | feature      |
      | secrets      |
      | caas         |
      | loadbalancer |
