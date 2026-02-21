from pytest_bdd import scenarios

# Load all scenario outlines from the feature file
# Step definitions are in conftest.py
scenarios("functional/deployments.feature")
