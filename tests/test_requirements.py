import os
from textwrap import dedent

import pytest
from pkg_resources import Requirement
from twitter.common.contextutil import temporary_dir

from pex.fetcher import PyPIFetcher
from pex.requirements import (
    Resolvable,
    ResolvableRepository,
    ResolvablePackage,
    ResolvableRequirement,
    RequirementsTxt,
    maybe_requirement,
    maybe_requirement_list,
    requirement_is_exact,
)


def test_from_empty_lines():
  reqs = RequirementsTxt.from_lines([])
  assert list(reqs.iter()) == []

  reqs = RequirementsTxt.from_lines(dedent("""
  # comment
  """).splitlines())
  assert list(reqs.iter()) == []


@pytest.mark.parametrize('flag_separator', (' ', '='))
def test_line_types(flag_separator):
  reqs = RequirementsTxt.from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  --allow-external%sspecific_requirement
  """ % flag_separator).splitlines())

  req_iter = reqs.iter()

  # simple_requirement
  req = next(req_iter)
  assert isinstance(req, ResolvableRequirement)
  assert req.requirement == Requirement.parse('simple_requirement')

  # specific_requirement
  req = next(req_iter)
  assert isinstance(req, ResolvableRequirement)
  assert req.requirement == Requirement.parse('specific_requirement==2')
  assert req._follow_links


def test_all_external():
  reqs = RequirementsTxt.from_lines(dedent("""
  simple_requirement
  specific_requirement==2
  --allow-all-external
  """).splitlines())
  reqs = list(reqs.iter())
  assert len(reqs) == 2
  assert reqs[0]._follow_links
  assert reqs[1]._follow_links


def test_index_types():
  reqs = RequirementsTxt()
  assert len(reqs._fetchers) == 1 and isinstance(reqs._fetchers[0], PyPIFetcher)

  reqs = RequirementsTxt.from_lines(dedent("""
  --no-index
  """).splitlines())
  assert reqs._fetchers == []

  for prefix in ('-f ', '--find-links ', '--find-links='):
    reqs = RequirementsTxt.from_lines(dedent("""
    --no-index
    %shttps://example.com/repo
    """ % prefix).splitlines())
    assert len(reqs._fetchers) == 1
    assert reqs._fetchers[0].urls('foo') == ['https://example.com/repo']

  for prefix in ('-i ', '--index-url ', '--index-url=', '--extra-index-url ', '--extra-index-url='):
    reqs = RequirementsTxt.from_lines(dedent("""
    --no-index
    %shttps://example.com/repo/
    """ % prefix).splitlines())
    assert len(reqs._fetchers) == 1, 'Prefix is: %r' % prefix
    assert reqs._fetchers[0].urls('foo') == ['https://example.com/repo/foo/']


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

    reqs = RequirementsTxt.from_file(os.path.join(td, 'requirements1.txt'))
    assert list(reqs.iter()) == [
      rr('requirement1'),
      rr('requirement2'),
      rr('requirement3'),
      rr('requirement4'),
    ]
