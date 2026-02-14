Feature: Deploy with external Juju controller
  As an operator
  I want to use an existing Juju controller for my OpenStack deployment
  So that I can consolidate Juju management across multiple deployments

  Background:
    Given an external Juju controller exists
    And the controller has a dedicated user with superuser permissions

  @provisioning
  @external-juju
  Scenario: Register external Juju controller
    Given I have the external controller details
    When I register the external Juju controller in Sunbeam
    Then the controller should be available in Sunbeam

  @provisioning
  @external-juju
  Scenario: Bootstrap cloud with external controller
    Given the external Juju controller is registered
    When I bootstrap the cloud with --controller option
    Then the cloud should use the external controller
    And all services should be deployed via the external controller
