Feature: Deploy with manual bare metal provider
  As an operator
  I want to deploy Canonical OpenStack using the manual bare metal provider
  So that I can use a single physical machine for testing

  Background:
    Given a machine meets minimum hardware requirements
    And Ubuntu Server 24.04 LTS is installed
    And the openstack snap is installed

  @provisioning
  @single-node
  Scenario: Prepare node for bootstrap
    Given the openstack snap is installed
    When I run the prepare-node-script
    Then the node should be ready for bootstrap

  @provisioning
  @single-node
  Scenario: Bootstrap single-node cloud
    Given the node is prepared
    When I bootstrap the cloud with default roles
    Then the cloud should be bootstrapped successfully
    And the cloud should have control, compute, and storage roles
