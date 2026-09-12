"""
Every serializer in the project can build its fields.

A serializer that cannot is a 500 on every endpoint that uses it. DRF raises
only when the fields are first accessed - at request time - so a serializer
with no test of its own fails silently until a user hits it. That is exactly
how SeekerProfileSerializer reached production broken.

This walks every apps.*.serializers module and instantiates each serializer,
so a new one is covered the day it is written.
"""

import importlib
import inspect
import pkgutil

import pytest
from rest_framework import serializers

import apps


def all_serializer_classes():
    found = []
    for module_info in pkgutil.walk_packages(apps.__path__, "apps."):
        if not module_info.name.endswith(".serializers"):
            continue
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, serializers.BaseSerializer)
                and obj.__module__ == module_info.name
            ):
                found.append(pytest.param(obj, id=f"{module_info.name}.{name}"))
    return found


SERIALIZERS = all_serializer_classes()


def test_the_search_found_the_serializers():
    """A typo in the walk would make every test below pass vacuously."""
    assert len(SERIALIZERS) > 40


@pytest.mark.regression
@pytest.mark.parametrize("serializer_class", SERIALIZERS)
def test_serializer_builds_its_fields(serializer_class):
    fields = serializer_class().fields

    assert len(fields) > 0
