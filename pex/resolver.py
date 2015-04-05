# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import time
from collections import defaultdict
from functools import partial

from pkg_resources import Distribution

from .base import maybe_requirement_list, requirement_is_exact
from .crawler import Crawler
from .fetcher import Fetcher, PyPIFetcher
from .http import Context
from .interpreter import PythonInterpreter
from .iterator import Iterator
from .orderedset import OrderedSet
from .package import Package, distribution_compatible
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


# Resolver.resolve() -> DistributionSet
#
#

class ResolvableSet(object):
  def __init__(self):

    self.__requirements = defaultdict(list)  # requirement.key => list of encountered requirements
    self.__distributions = {}  # Package => Distribution


class ResolverOptions(object):
  @classmethod
  def from_requirements_txt(cls, requirements_txt):
    pass

  def __init__(self):
    self._fetchers = []
    self._allow_all_external = False
    self._allow_external = set()
    self._allow_unverified = set()

  def add_index(self, index):
    self._fetchers.append(PyPIFetcher(index))

  def add_repository(self, repo):
    self._fetchers.append(Fetcher([repo]))

  def clear_indices(self):
    self._fetchers = [fetcher for fetcher in self._fetchers if not isinstance(fetcher, PyPIFetcher)]

  def allow_all_external(self):
    self._allow_all_external = True

  def allow_external(self, key):
    self._allow_external.add(safe_name(key).lower())

  def allow_unverified(self, key):
    self._allow_unverified.add(safe_name(key).lower())

  def allows_external(self, key):
    return self._allow_all_external or key in self._allow_external

  def allows_unverified(self, key):
    return key in self._allow_unverified

  # ---

  def get_context(self, key):
    return Context.get()

  def get_crawler(self, key):
    return Crawler(self.get_context(key))

  def get_iterator(self, key):
    return Iterator(
        fetchers=self._fetchers,
        crawler=self.get_crawler(key),
        precedence=self._precedence,
        follow_links=self._options.allows_external(resolvable.name)
    )



class Resolver(object):
  @classmethod
  def from_requirements(cls, requirements_txt):
    rtxt = RequirementsTxt.from_file(requirements_txt)
    return cls(

    )


  def __init__(self,
               interpreter=None,
               platform=None,
               context=None,
               translator=None,
               options=None):
    """
    fetchers=None,
      | --no-index
      | -i / --index-url / --extra-index-url
      | -f / --find-links
    translator=None,
    interpreter=None,  | pex only
    platform=None,     | pex only
    context=None,
      | --allow-insecure
      | --allow-unverified
    threads=1,
    precedence=None,
      | --no-use-wheel
    cache=None,        | pex only
    cache_ttl=None):   | pex only
    prerelease=False   | pex only

    crawler
    | --allow-external
    | --allow-all-external

    -----------

    cache=True ==>
      fetchers updated
      iterator chained
    """
    self.__cache = cache
    self.__cache_ttl = cache_ttl
    self._distributions = _DistributionCache()

  def __package_iterator(self, resolvable, existing=None):
    if existing is None:
      iterator = Iterator(
          fetchers=self._fetchers,
          crawler=self._crawler,
          precedence=self._precedence,
          follow_links=self._options.allows_external(resolvable.name))
      existing = resolvable.packages(iterator)

    return [package for package in existing
            #if package.satisfies(requirement) and
            if package.compatible(interpreter.identity, platform)]

  # A caching wrapper around packages_from_requirement
  #
  # The algorithm works as following:
  #   - If the requirement is exact and we get a local match, short circuit and consider
  #     the package list complete.
  #   - If the requirement is not exact but a ttl is suppled, consider inexact matches so long
  #     as they were resolved fewer than ttl seconds ago.
  #   - If none of the above are met, fall back to iterator.
  def __package_iterator_cached(self, resolvable, existing=None):
    iterator = Iterator(
        fetchers=Fetcher([self.__cache]),
        crawler=self._crawler,
        precedence=self._precedence,
        follow_links=False)
    packages = resolvable.packages(iterator)

    if packages:
      # match with exact requirement, always accept.
      if resolvable.exact:
        #TRACER.log('Package cache hit: %s' % resolvable, V=3)
        return packages

      # match with inexact requirement, consider if ttl supplied.
      if ttl:
        now = time.time()
        packages = [package for package in packages if package.remote or package.local and
            (now - os.path.getmtime(package.path)) < ttl]
        if packages:
          #TRACER.log('Package cache hit (inexact): %s' % requirement, V=3)
          return packages

    # no matches in the local cache
    #TRACER.log('Package cache miss: %s' % requirement, V=3)
    return self.__package_iterator(resolvable, existing=existing)

  def __requires(self, package, extras):
    pass

  def resolve(self, resolvable, requirement_set=None):
    requirement_set = requirement_set or defaultdict(list)

    while True:
      while requirements:
        requirement = requirements.pop(0)
        requirement_set[requirement.key].append(requirement)
        distribution_list = distribution_set[requirement.key] = self.__package_iterator(
            requirement, distributions)
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

    return requirement_set

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
    local_iterator = Iterator(fetchers=[local_fetcher], crawler=crawler, precedence=precedence)
    package_iterator = partial(packages_from_requirement_cached, local_iterator, cache_ttl)
  else:
    package_iterator = packages_from_requirement

  iterator = Iterator(fetchers=fetchers, crawler=crawler, precedence=precedence)

  requirements = maybe_requirement_list(requirements)
  distribution_set = defaultdict(list)
  requirement_set = defaultdict(list)
  processed_requirements = set()
  """

  """
    requirements,
    fetchers=None,
      | --no-index
      | -i / --index-url / --extra-index-url
      | -f / --find-links
    translator=None,
      | --no-use-wheel
    interpreter=None,  | pex only
    platform=None,     | pex only
    context=None,
      | --allow-unverified
    threads=1,
    precedence=None,
    cache=None,
    cache_ttl=None):

    crawler
    | --allow-external
    | --allow-all-external
  """


def resolve(
    requirements,
    fetchers=None,
    translator=None,
    interpreter=None,
    platform=None,
    context=None,
    threads=1,
    precedence=None,
    cache=None,
    cache_ttl=None):

  resolver = Resolver(
      translator=translator,
      interpreter=interpreter,
      platform=platform,
      context=context,
      threads=threads,
      precedence=precedence,
      cache=cache,
      cache_ttl=cache_ttl,
      options=ResolverOptions.default())

  resolvables = [ResolvableRequirement.from_string(req) for req in requirements]
  return resolver.resolve(resolvables)


def resolve(
    requirements,
    fetchers=None,
    translator=None,
    interpreter=None,
    platform=None,
    context=None,
    threads=1,
    precedence=None,
    cache=None,
    cache_ttl=None):

  """Produce all distributions needed to (recursively) meet `requirements`

  :param requirements: An iterator of Requirement-like things, either
    :class:`pkg_resources.Requirement` objects or requirement strings.
  :keyword fetchers: (optional) A list of :class:`Fetcher` objects for locating packages.  If
    unspecified, the default is to look for packages on PyPI.
  :keyword translator: (optional) A :class:`Translator` object for translating packages into
    distributions.  If unspecified, the default is constructed from `Translator.default`.
  :keyword interpreter: (optional) A :class:`PythonInterpreter` object to use for building
    distributions and for testing distribution compatibility.
  :keyword platform: (optional) A PEP425-compatible platform string to use for filtering
    compatible distributions.  If unspecified, the current platform is used, as determined by
    `Platform.current()`.
  :keyword context: (optional) A :class:`Context` object to use for network access.  If
    unspecified, the resolver will attempt to use the best available network context.
  :keyword threads: (optional) A number of parallel threads to use for resolving distributions.
    By default 1.
  :type threads: int
  :keyword precedence: (optional) An ordered list of allowable :class:`Package` classes
    to be used for producing distributions.  For example, if precedence is supplied as
    ``(WheelPackage, SourcePackage)``, wheels will be preferred over building from source, and
    eggs will not be used at all.  If ``(WheelPackage, EggPackage)`` is supplied, both wheels and
    eggs will be used, but the resolver will not resort to building anything from source.
  :keyword cache: (optional) A directory to use to cache distributions locally.
  :keyword cache_ttl: (optional integer in seconds) If specified, consider non-exact matches when
    resolving requirements.  For example, if ``setuptools==2.2`` is specified and setuptools 2.2 is
    available in the cache, it will always be used.  However, if a non-exact requirement such as
    ``setuptools>=2,<3`` is specified and there exists a setuptools distribution newer than
    cache_ttl seconds that satisfies the requirement, then it will be used.  If the distribution
    is older than cache_ttl seconds, it will be ignored.  If ``cache_ttl`` is not specified,
    resolving inexact requirements will always result in making network calls through the
    ``context``.
  :returns: List of :class:`pkg_resources.Distribution` instances meeting ``requirements``.
  :raises Unsatisfiable: If ``requirements`` is not transitively satisfiable.
  :raises Untranslateable: If no compatible distributions could be acquired for
    a particular requirement.

  This method improves upon the setuptools dependency resolution algorithm by maintaining sets of
  all compatible distributions encountered for each requirement rather than the single best
  distribution encountered for each requirement.  This prevents situations where ``tornado`` and
  ``tornado==2.0`` could be treated as incompatible with each other because the "best
  distribution" when encountering ``tornado`` was tornado 3.0.  Instead, ``resolve`` maintains the
  set of compatible distributions for each requirement as it is encountered, and iteratively filters
  the set.  If the set of distributions ever becomes empty, then ``Unsatisfiable`` is raised.

  .. versionchanged:: 0.8
    A number of keywords were added to make requirement resolution slightly easier to configure.
    The optional ``obtainer`` keyword was replaced by ``fetchers``, ``translator``, ``context``,
    ``threads``, ``precedence``, ``cache`` and ``cache_ttl``, also all optional keywords.
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
    local_iterator = Iterator(fetchers=[local_fetcher], crawler=crawler, precedence=precedence)
    package_iterator = partial(packages_from_requirement_cached, local_iterator, cache_ttl)
  else:
    package_iterator = packages_from_requirement

  iterator = Iterator(fetchers=fetchers, crawler=crawler, precedence=precedence)

  requirements = maybe_requirement_list(requirements)
  distribution_set = defaultdict(list)
  requirement_set = defaultdict(list)
  processed_requirements = set()

  def requires(package, requirement):
    if not distributions.has(package):
      with TRACER.timed('Fetching %s' % package.url, V=2):
        local_package = Package.from_href(context.fetch(package, into=cache))
      if package.remote:
        # this was a remote resolution -- so if we copy from remote to local but the
        # local already existed, update the mtime of the local so that it is correct
        # with respect to cache_ttl.
        os.utime(local_package.path, None)
      with TRACER.timed('Translating %s into distribution' % local_package.path, V=2):
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
