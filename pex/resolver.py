# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import shutil
import time
from collections import defaultdict

from pkg_resources import safe_name

from .crawler import Crawler
from .fetcher import Fetcher, PyPIFetcher
from .http import Context
from .installer import EggInstaller, WheelInstaller
from .interpreter import PythonInterpreter
from .iterator import Iterator, IteratorInterface
from .package import EggPackage, Package, SourcePackage, WheelPackage, distribution_compatible
from .platforms import Platform
from .resolvable import ResolvableRequirement, resolvables_from_iterable
from .sorter import Sorter
from .tracer import TRACER
from .translator import (
    ChainedTranslator,
    EggTranslator,
    SourceTranslator,
    WheelTranslator
)


class Untranslateable(Exception):
  pass


class Unsatisfiable(Exception):
  pass


class StaticIterator(IteratorInterface):
  """An iterator that iterates over a static list of packages."""

  def __init__(self, packages):
    self._packages = packages

  def iter(self, req):
    for package in self._packages:
      if package.satisfies(req):
        yield package


# An internal set of resolvables/packages, not part of the public API.
class ResolvableSet(object):
  class Error(Exception): pass
  class Unsatisfiable(Error): pass

  def __init__(self):
    self.__resolvables = defaultdict(set)
    self.__packages = defaultdict(list)

  def merge(self, resolvable, packages):
    """Add a resolvable and its resolved packages."""
    self.__resolvables[resolvable.name].add(resolvable)
    if self.__packages[resolvable.name]:
      self.__packages[resolvable.name] = (
          set(packages).intersection(self.__packages[resolvable.name]))
    else:
      self.__packages[resolvable.name] = set(packages)
    if not self.__packages[resolvable.name]:
      raise self.Unsatisfiable('Could not satisfy all requirements:\n%s' % '\n'.join(
          map(str, self.__resolvables[resolvable.name])))

  def get(self, name):
    return list(self.__packages.get(name, []))  # make a copy

  def packages(self):
    """Returns a mapping of name => best package for resolvables in this ResolvableSet."""
    return self.__packages.copy()

  def extras(self, name):
    return set.union(*[set(resolvable.extras()) for resolvable in self.__resolvables[name]])


class ResolverOptionsBuilder(object):
  """A helper that processes options into a ResolverOptions object.

  Used by command-line and requirements.txt processors to configure a resolver.
  """

  def __init__(self):
    self._fetchers = [PyPIFetcher()]
    self._allow_all_external = False
    self._allow_external = set()
    self._allow_unverified = set()
    self._precedence = Sorter.DEFAULT_PACKAGE_PRECEDENCE
    self._context = Context.get()

  # TODO(wickman) Resolve duplicates here
  def add_index(self, index):
    self._fetchers.append(PyPIFetcher(index))
    return self

  def set_index(self, index):
    self._fetchers = [PyPIFetcher(index)]
    return self

  def add_repository(self, repo):
    self._fetchers.append(Fetcher([repo]))
    return self

  def clear_indices(self):
    self._fetchers = [fetcher for fetcher in self._fetchers if not isinstance(fetcher, PyPIFetcher)]
    return self

  def allow_all_external(self):
    self._allow_all_external = True
    return self

  def allow_external(self, key):
    self._allow_external.add(safe_name(key).lower())
    return self

  def allow_unverified(self, key):
    self._allow_unverified.add(safe_name(key).lower())
    return self

  def use_wheel(self):
    if WheelPackage not in self._precedence:
      self._precedence = (WheelPackage,) + self._precedence
    return self

  def no_use_wheel(self):
    self._precedence = tuple(
        [precedent for precedent in self._precedence if precedent is not WheelPackage])
    return self

  def allow_builds(self):
    if SourcePackage not in self._precedence:
      self._precedence = self._precedence + (SourcePackage,)
    return self

  def no_allow_builds(self):
    self._precedence = tuple(
        [precedent for precedent in self._precedence if precedent is not SourcePackage])
    return self

  def set_context(self, context):
    self._context = context
    return self

  def set_precedence(self, precedence):
    self._precedence = precedence
    return self

  def build(self):
    return ResolverOptions(
        self._fetchers,
        self._allow_all_external,
        self._allow_external,
        self._allow_unverified,
        self._precedence,
        self._context,
    )


class ResolverOptions(object):
  def __init__(self,
               fetchers=None,
               allow_all_external=False,
               allow_external=frozenset(),
               allow_unverified=frozenset(),
               precedence=None,
               context=None):
    self._fetchers = fetchers or [PyPIFetcher()]
    self._allow_all_external = allow_all_external
    self._allow_external = allow_external
    self._allow_unverified = allow_unverified
    self._precedence = precedence or Sorter.DEFAULT_PACKAGE_PRECEDENCE
    self._context = context or Context.get()  # TODO(wickman) Revisit with #58

  def get_context(self, key):
    return self._context

  def get_crawler(self, key):
    return Crawler(self.get_context(key))

  def get_sorter(self):
    return Sorter(self._precedence)

  def get_translator(self, interpreter, platform):
    translators = []

    # TODO(wickman) This is not ideal -- consider an explicit link between a Package
    # and its Installer type rather than mapping this here, precluding the ability to
    # easily add new package types (or we just forego that forever.)
    for package in self._precedence:
      if package is WheelPackage:
        translators.append(WheelTranslator(interpreter=interpreter, platform=platform))
      elif package is EggPackage:
        translators.append(EggTranslator(interpreter=interpreter, platform=platform))
      elif package is SourcePackage:
        installer_impl = WheelInstaller if WheelPackage in self._precedence else EggInstaller
        translators.append(SourceTranslator(installer_impl=installer_impl, interpreter=interpreter))

    return ChainedTranslator(*translators)

  def get_iterator(self, key):
    return Iterator(
        fetchers=self._fetchers,
        crawler=self.get_crawler(key),
        follow_links=self._allow_all_external or key in self._allow_external,
    )


class Resolver(object):
  """Interface for resolving resolvable entities into python packages."""

  class Error(Exception): pass

  @classmethod
  def filter_packages_by_interpreter(cls, packages, interpreter, platform):
    return [package for package in packages
        if package.compatible(interpreter.identity, platform)]

  def __init__(self,
               interpreter=None,
               platform=None,
               options=None):
    self._interpreter = interpreter or PythonInterpreter.get()
    self._platform = platform or Platform.current()
    self._options = options or ResolverOptions()

  def package_iterator(self, resolvable, existing=None):
    if existing:
      iterator = StaticIterator(existing)
    else:
      iterator = self._options.get_iterator(resolvable.name)
    existing = resolvable.packages(iterator)
    return self.filter_packages_by_interpreter(existing, self._interpreter, self._platform)

  def build(self, package):
    context = self._options.get_context(package.name)
    translator = self._options.get_translator(self._interpreter, self._platform)
    with TRACER.timed('Fetching %s' % package.url, V=2):
      local_package = Package.from_href(context.fetch(package))
    with TRACER.timed('Translating %s into distribution' % local_package.path, V=2):
      dist = translator.translate(local_package)
    if dist is None:
      raise Untranslateable('Package %s is not translateable by %s' % (package, translator))
    if not distribution_compatible(dist, self._interpreter, self._platform):
      raise Untranslateable('Could not get distribution for %s on appropriate platform.' % package)
    return dist

  def resolve(self, resolvables, resolvable_set=None):
    resolvables = list(resolvables)
    resolvable_set = resolvable_set or ResolvableSet()
    processed_resolvables = set()
    processed_packages = {}
    distributions = {}
    sorter = self._options.get_sorter()

    while resolvables:
      while resolvables:
        resolvable = resolvables.pop(0)
        if resolvable in processed_resolvables:
          continue
        packages = self.package_iterator(resolvable, existing=resolvable_set.get(resolvable.name))
        resolvable_set.merge(resolvable, packages)
        processed_resolvables.add(resolvable)

      packages = dict(
          (name, sorter.sort(packages)[0])
          for (name, packages) in resolvable_set.packages().items())

      for resolvable_name, package in packages.items():
        if resolvable_name in processed_packages:
          if package != processed_packages[resolvable_name]:
            raise self.Error('Ambiguous resolvable: %s' % resolvable_name)
          continue
        if package not in distributions:
          distributions[package] = self.build(package)
        distribution = distributions[package]
        processed_packages[resolvable_name] = package
        resolvables.extend(ResolvableRequirement(req) for req in
            distribution.requires(extras=resolvable_set.extras(resolvable_name)))

    return list(distributions.values())


class CachingResolver(Resolver):
  """A package resolver implementing a package cache."""

  @classmethod
  def filter_packages_by_ttl(cls, packages, ttl, now=None):
    now = now if now is not None else time.time()
    return [package for package in packages
        if package.remote or package.local and (now - os.path.getmtime(package.path)) < ttl]

  def __init__(self, cache, cache_ttl, *args, **kw):
    self.__cache = cache
    self.__cache_ttl = cache_ttl
    super(CachingResolver, self).__init__(*args, **kw)

  # Short-circuiting package iterator.
  def package_iterator(self, resolvable, existing=None):
    sorter = self._options.get_sorter()
    iterator = Iterator(fetchers=[Fetcher([self.__cache])])
    packages = sorter.sort(resolvable.packages(iterator))

    if packages:
      if resolvable.exact:
        return packages

      if self.__cache_ttl:
        packages = self.filter_packages_by_ttl(packages, self.__cache_ttl)
        if packages:
          return packages

    return super(CachingResolver, self).package_iterator(resolvable, existing=existing)

  # Caching sandwich.
  def build(self, package):
    # cache package locally
    if package.remote:
      package = Package.from_href(
          self._options.get_context(package.name).fetch(package, into=self.__cache))
      os.utime(package.path, None)
    # build into distribution
    dist = super(CachingResolver, self).build(package)
    # if distribution is not in cache, copy
    target = os.path.join(self.__cache, os.path.basename(dist.location))
    if not os.path.exists(target):
      shutil.copyfile(dist.location, target + '~')
      os.rename(target + '~', target)
    os.utime(target, None)
    return dist


def resolve(
    requirements,
    fetchers=None,
    interpreter=None,
    platform=None,
    context=None,
    precedence=None,
    cache=None,
    cache_ttl=None):

  """Produce all distributions needed to (recursively) meet `requirements`

  :param requirements: An iterator of Requirement-like things, either
    :class:`pkg_resources.Requirement` objects or requirement strings.
  :keyword fetchers: (optional) A list of :class:`Fetcher` objects for locating packages.  If
    unspecified, the default is to look for packages on PyPI.
  :keyword interpreter: (optional) A :class:`PythonInterpreter` object to use for building
    distributions and for testing distribution compatibility.
  :keyword platform: (optional) A PEP425-compatible platform string to use for filtering
    compatible distributions.  If unspecified, the current platform is used, as determined by
    `Platform.current()`.
  :keyword context: (optional) A :class:`Context` object to use for network access.  If
    unspecified, the resolver will attempt to use the best available network context.
  :type threads: int
  :keyword precedence: (optional) An ordered list of allowable :class:`Package` classes
    to be used for producing distributions.  For example, if precedence is supplied as
    ``(WheelPackage, SourcePackage)``, wheels will be preferred over building from source, and
    eggs will not be used at all.  If ``(WheelPackage, EggPackage)`` is suppplied, both wheels and
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

  .. versionchanged:: 1.0
    The ``translator`` and ``threads`` keywords have been removed.  The choice of threading
    policy is now implicit.  The choice of translation policy is dictated by ``precedence``
    directly.

  .. versionchanged:: 1.0
    ``resolver`` is now just a wrapper around the :class:`Resolver` and :class:`CachingResolver`
    classes.
  """

  options = ResolverOptions(
      fetchers=fetchers,
      precedence=precedence,
      context=context,
  )

  keywords = dict(
      interpreter=interpreter,
      platform=platform,
      options=options,
  )

  if cache:
    resolver = CachingResolver(cache, cache_ttl, **keywords)
  else:
    resolver = Resolver(**keywords)

  return resolver.resolve(resolvables_from_iterable(requirements))
