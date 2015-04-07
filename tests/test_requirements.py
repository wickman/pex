import os
from textwrap import dedent

import pytest
from pkg_resources import Requirement, safe_name
from twitter.common.contextutil import temporary_dir

from pex.fetcher import PyPIFetcher
from pex.resolvable import (
    Resolvable,
    ResolvableRepository,
    ResolvablePackage,
    ResolvableRequirement,
)
from pex.resolver import ResolverOptions, ResolverOptionsBuilder
from pex.requirements import requirements_from_lines, requirements_from_file


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
  with temporary_dir() as td:
    # TODO(wickman) It seems crazy that requirements.txt would not support relativized
    # paths.
    with open(os.path.join(td, 'requirements1.txt'), 'w') as fp:
      fp.write(dedent('''
      requirement1
      requirement2
      -r %s
      ''' % os.path.join(td, 'requirements2.txt')))

    with open(os.path.join(td, 'requirements2.txt'), 'w') as fp:
      fp.write(dedent('''
      requirement3
      requirement4
      '''))

    def rr(req):
      return ResolvableRequirement(Requirement.parse(req))

    reqs, builder = requirements_from_file(os.path.join(td, 'requirements1.txt'))
    assert reqs == [
      rr('requirement1'),
      rr('requirement2'),
      rr('requirement3'),
      rr('requirement4'),
    ]
