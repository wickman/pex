# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.common import safe_copy
from pex.fetcher import Fetcher
from pex.package import SourcePackage, EggPackage
from pex.resolver import resolve, _ResolvableSet
from pex.resolvable import ResolvableRequirement
from pex.testing import make_sdist

import mock
import pytest
from twitter.common.contextutil import temporary_dir


def test_empty_resolve():
  empty_resolve = resolve([])
  assert empty_resolve == []

  with temporary_dir() as td:
    empty_resolve = resolve([], cache=td)
    assert empty_resolve == []


def test_simple_local_resolve():
  project_sdist = make_sdist(name='project')

  with temporary_dir() as td:
    safe_copy(project_sdist, os.path.join(td, os.path.basename(project_sdist)))
    fetchers = [Fetcher([td])]
    dists = resolve(['project'], fetchers=fetchers)
    assert len(dists) == 1


def test_resolvable_set():
  rs = _ResolvableSet()
  rq = ResolvableRequirement.from_string('foo[ext]')
  source_pkg = SourcePackage.from_href('foo-2.3.4.tar.gz')
  binary_pkg = EggPackage.from_href('foo-2.3.4-py3.4.egg')

  rs.merge(rq, [source_pkg, binary_pkg])
  assert rs.get('foo') == set([source_pkg, binary_pkg])
  assert rs.packages() == {'foo': set([source_pkg, binary_pkg])}

  # test immutability
  packages = rs.packages()
  packages['foo'] = []
  assert rs.get('foo') == set([source_pkg, binary_pkg])

  # test methods
  assert rs.extras('foo') == set(['ext'])

  # test filtering
  rs.merge(rq, [source_pkg])
  assert rs.get('foo') == set([source_pkg])

  with pytest.raises(_ResolvableSet.Unsatisfiable):
    rs.merge(rq, [binary_pkg])


# TODO(wickman) Write more than simple resolver test.
