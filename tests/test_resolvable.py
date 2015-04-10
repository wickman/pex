# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.iterator import Iterator
from pex.package import SourcePackage, Package
from pex.resolvable import (
    Resolvable,
    ResolvablePackage,
    ResolvableRepository,
    ResolvableRequirement,
    resolvables_from_iterable,
)

import pkg_resources
import pytest

try:
  from unittest import mock
except ImportError:
  import mock


def test_resolvable_package():
  source_name = 'foo-2.3.4.tar.gz'
  pkg = SourcePackage.from_href(source_name)
  resolvable = ResolvablePackage.from_string(source_name)

  mock_iterator = mock.create_autospec(Iterator, spec_set=True)
  mock_iterator.iter.return_value = iter([])
  assert resolvable.packages(mock_iterator) == [pkg]
  # fetchers are currently unused for static packages.
  assert mock_iterator.iter.mock_calls == []
  assert resolvable.name == 'foo'
  assert resolvable.exact is True
  # TODO(wickman) Implement extras parsing for resolvable packages.
  assert resolvable.extras() == []

  assert Resolvable.get('foo-2.3.4.tar.gz') == ResolvablePackage(pkg)

  with pytest.raises(ResolvablePackage.InvalidRequirement):
    ResolvablePackage.from_string('foo')


def test_resolvable_repository():
  # not yet implemented
  with pytest.raises(Resolvable.InvalidRequirement):
    ResolvableRepository.from_string('git+http://github.com/wickman/pex')


def test_resolvable_requirement():
  req = 'foo[bar]==2.3.4'
  resolvable = ResolvableRequirement.from_string(req)
  assert resolvable.requirement == pkg_resources.Requirement.parse('foo[bar]==2.3.4')
  assert resolvable.name == 'foo'
  assert resolvable.exact is True  # TODO(wickman) test inexact
  assert resolvable.extras() == ['bar']

  source_pkg = SourcePackage.from_href('foo-2.3.4.tar.gz')
  mock_iterator = mock.create_autospec(Iterator, spec_set=True)
  mock_iterator.iter.return_value = iter([source_pkg])
  assert resolvable.packages(mock_iterator) == [source_pkg]
  assert mock_iterator.iter.mock_calls == [
      mock.call(pkg_resources.Requirement.parse('foo[bar]==2.3.4'))]

  # test non-exact
  resolvable = ResolvableRequirement.from_string('foo')
  assert resolvable.exact is False

  # test Resolvable.get, which should delegate to a ResolvableRequirement in this case
  assert Resolvable.get('foo') == ResolvableRequirement.from_string('foo')


def test_resolvables_from_iterable():
  reqs = [
      'foo',  # string
      Package.from_href('foo-2.3.4.tar.gz'),  # Package
      pkg_resources.Requirement.parse('foo==2.3.4'),
  ]

  resolved_reqs = list(resolvables_from_iterable(reqs))

  assert resolved_reqs == [
      ResolvableRequirement.from_string('foo'),
      ResolvablePackage.from_string('foo-2.3.4.tar.gz'),
      ResolvableRequirement.from_string('foo==2.3.4'),
  ]
