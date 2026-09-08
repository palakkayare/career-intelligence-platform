"""
Career intelligence app structure tests.
"""
import pytest
from django.core.management import get_commands


@pytest.mark.regression
@pytest.mark.parametrize('command', [
    'seed_target_roles',
    'seed_learning_resources',
    'seed_career_paths',
])
def test_seed_commands_are_discoverable(command):
    """
    Regression: apps/career_intel/management/ was missing __init__.py. Python's
    implicit namespace packages kept discovery working locally, but that is a
    fallback, not a guarantee — packaging steps and container builds that
    filter on __init__.py can drop the directory entirely.
    """
    assert command in get_commands(), (
        f'{command} is not discoverable - check that '
        'apps/career_intel/management/__init__.py exists'
    )