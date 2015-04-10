# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

import pytest
from pkg_resources import Requirement, safe_name
from twitter.common.contextutil import temporary_dir

from pex.requirements import requirements_from_file, requirements_from_lines
from pex.resolvable import ResolvableRequirement


def test_from_empty_lines():
  reqs, _ = requirements_from_lines([])
  assert len(reqs) == 0

  reqs, _ = requirements_from_lines(dedent("""
  # comment
  """).splitlines())
  assert len(reqs) == 0


@pytest.mark.parametrize('flag_separator', (' ', '='))
def test_line_types(flag_separator):
  reqs, builder = requirements_from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  --allow-external%sspecific_requirement
  """ % flag_separator).splitlines())

  # simple_requirement
  assert len(reqs) == 2

  assert isinstance(reqs[0], ResolvableRequirement)
  assert reqs[0].requirement == Requirement.parse('simple_requirement')

  # specific_requirement
  assert isinstance(reqs[1], ResolvableRequirement)
  assert reqs[1].requirement == Requirement.parse('specific_requirement==2')
  assert safe_name('specific_requirement') in builder._allow_external


def test_all_external():
  reqs, builder = requirements_from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  --allow-all-external
  """).splitlines())
  assert builder._allow_all_external


def test_index_types():
  reqs, builder = requirements_from_lines(dedent("""
  --no-index
  """).splitlines())
  assert builder._fetchers == []

  for prefix in ('-f ', '--find-links ', '--find-links='):
    reqs, builder = requirements_from_lines(dedent("""
    --no-index
    %shttps://example.com/repo
    """ % prefix).splitlines())
    assert len(builder._fetchers) == 1
    assert builder._fetchers[0].urls('foo') == ['https://example.com/repo']

  for prefix in ('-i ', '--index-url ', '--index-url=', '--extra-index-url ', '--extra-index-url='):
    reqs, builder = requirements_from_lines(dedent("""
    --no-index
    %shttps://example.com/repo/
    """ % prefix).splitlines())
    assert len(builder._fetchers) == 1, 'Prefix is: %r' % prefix
    assert builder._fetchers[0].urls('foo') == ['https://example.com/repo/foo/']


def test_nested_requirements():
  with temporary_dir() as td1:
    with temporary_dir() as td2:
      with open(os.path.join(td1, 'requirements.txt'), 'w') as fp:
        fp.write(dedent('''
            requirement1
            requirement2
            -r %s
            -r %s
        ''' % (
            os.path.join(td2, 'requirements_nonrelative.txt'),
            os.path.join(td1, 'relative', 'requirements_relative.txt'))
        ))

      with open(os.path.join(td2, 'requirements_nonrelative.txt'), 'w') as fp:
        fp.write(dedent('''
        requirement3
        requirement4
        '''))

      os.mkdir(os.path.join(td1, 'relative'))
      with open(os.path.join(td1, 'relative', 'requirements_relative.txt'), 'w') as fp:
        fp.write(dedent('''
        requirement5
        requirement6
        '''))

      def rr(req):
        return ResolvableRequirement(Requirement.parse(req))

      reqs, builder = requirements_from_file(os.path.join(td1, 'requirements.txt'))
      assert reqs == [rr('requirement%d' % k) for k in (1, 2, 3, 4, 5, 6)]
