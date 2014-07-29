# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

from collections import defaultdict
from functools import partial

from pkg_resources import Distribution

from .base import maybe_requirement_list, requirement_is_exact
from .crawler import Crawler
from .http import Context
from .interpreter import PythonInterpreter
from .iterator import Iterator
from .fetcher import Fetcher, PyPIFetcher
from .orderedset import OrderedSet
from .package import distribution_compatible, Package
from .platforms import Platform
from .tracer import TRACER
from .translator import Translator


class Untranslateable(Exception):
  pass


class Unsatisfiable(Exception):
  pass


class _DistributionCache(object):
  _ERROR_MSG = 'Expected %s but got %s'

  def __init__(self):
    self._translated_packages = {}

  def has(self, package):
    if not isinstance(package, Package):
      raise ValueError(self._ERROR_MSG % (Package, package))
    return package in self._translated_packages

  def put(self, package, distribution):
    if not isinstance(package, Package):
      raise ValueError(self._ERROR_MSG % (Package, package))
    if not isinstance(distribution, Distribution):
      raise ValueError(self._ERROR_MSG % (Distribution, distribution))
    self._translated_packages[package] = distribution

  def get(self, package):
    if not isinstance(package, Package):
      raise ValueError(self._ERROR_MSG % (Package, package))
    return self._translated_packages[package]


def packages_from_requirement(
    iterator,
    requirement,
    interpreter,
    platform,
    existing=None):

  with TRACER.timed('Resolving %s' % requirement, V=2):
    if existing is None:
      existing = iterator.iter(requirement)

    return [package for package in existing
            if package.satisfies(requirement)
            and package.compatible(interpreter.identity, platform)]


# A caching wrapper around packages_from_requirement
#
# The algorithm works as following:
#   - If the requirement is exact and we get a local match, short circuit and consider
#     the package list complete.
#   - TODO: If the requirement is not exact but the returned package mtime
#     is below the ttl, then we allow it to be used.
#   - If none of the above are met, fall back to iterator.
def packages_from_requirement_cached(local_iterator, iterator, requirement, *args, **kw):
  packages = packages_from_requirement(local_iterator, requirement, *args, **kw)

  if requirement_is_exact(requirement) and packages:
    TRACER.log('Package cache hit: %s' % requirement, V=3)
    return packages

  TRACER.log('Package cache miss: %s' % requirement, V=3)
  return packages_from_requirement(iterator, requirement, *args, **kw)


def resolve(
    requirements,  # Requirement iterator (e.g. RequirementsTxt or list of strings)
    fetchers=None,  # how to locate
    translator=None,  # package link -> distribution
    interpreter=None,  # interpreter with which to build/filter source packages
    platform=None,  # platform with which to filter distributions
    context=None,  # request context for network connectivity
    threads=1,  # how many threads to use when resolving
    precedence=None,  # ...
    cache=None):  # fetch cache for things

  """List all distributions needed to (recursively) meet `requirements`

  When resolving dependencies, multiple (potentially incompatible) requirements may be encountered.
  Handle this situation by iteratively filtering a set of potential project
  distributions by new requirements, and finally choosing the highest version meeting all
  requirements, or raise an error indicating unsatisfiable requirements.

  Note: should `pkg_resources.WorkingSet.resolve` correctly handle multiple requirements in the
  future this should go away in favor of using what setuptools provides.

  :returns: List of :class:`pkg_resources.Distribution` instances meeting `requirements`.
  """
  distributions = _DistributionCache()
  interpreter = interpreter or PythonInterpreter.get()
  platform = platform or Platform.current()
  context = context or Context.get()
  crawler = Crawler(context, threads=threads)
  fetchers = fetchers[:] if fetchers is not None else [PyPIFetcher()]
  translator = translator or Translator.default(interpreter=interpreter, platform=platform)

  if cache:
    local_fetcher = Fetcher([cache])
    fetchers.insert(0, local_fetcher)
    local_iterator = Iterator(fetchers=[local_fetcher], crawler=crawler, precedence=precedence)
    package_iterator = partial(packages_from_requirement_cached, local_iterator)
  else:
    package_iterator = packages_from_requirement

  iterator = Iterator(fetchers=fetchers, crawler=crawler, precedence=precedence)

  requirements = maybe_requirement_list(requirements)
  # requirements = RequirementsTxt.wrap(requirements)
  distribution_set = defaultdict(list)
  requirement_set = defaultdict(list)
  processed_requirements = set()

  def requires(package, requirement):
    if not distributions.has(package):
      local_package = Package.from_href(context.fetch(package, into=cache))
      dist = translator.translate(local_package, into=cache)
      if dist is None:
        raise Untranslateable('Package %s is not translateable.' % package)
      if not distribution_compatible(dist, interpreter, platform):
        raise Untranslateable('Could not get distribution for %s on appropriate platform.' %
            package)
      distributions.put(package, dist)
    dist = distributions.get(package)
    return dist.requires(extras=requirement.extras)

  while True:
    while requirements:
      requirement = requirements.pop(0)
      requirement_set[requirement.key].append(requirement)
      distribution_list = distribution_set[requirement.key] = package_iterator(
          iterator,
          requirement,
          interpreter,
          platform,
          existing=distribution_set.get(requirement.key))
      if not distribution_list:
        raise Unsatisfiable('Cannot satisfy requirements: %s' % requirement_set[requirement.key])

    # get their dependencies
    for requirement_key, requirement_list in requirement_set.items():
      new_requirements = OrderedSet()
      highest_package = distribution_set[requirement_key][0]
      for requirement in requirement_list:
        if requirement in processed_requirements:
          continue
        new_requirements.update(requires(highest_package, requirement))
        processed_requirements.add(requirement)
      requirements.extend(list(new_requirements))

    if not requirements:
      break

  to_activate = set()
  for distribution_list in distribution_set.values():
    to_activate.add(distributions.get(distribution_list[0]))
  return to_activate
