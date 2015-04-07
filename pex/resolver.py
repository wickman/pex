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
    Translator,
    WheelTranslator
)


class Untranslateable(Exception):
  pass


class Unsatisfiable(Exception):
  pass


class StaticIterator(IteratorInterface):
  def __init__(self, packages):
    self._packages = packages

  def iter(self, req):
    for package in self._packages:
      if package.satisfies(req):
        yield package


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
  def __init__(self):
    self._fetchers = [PyPIFetcher()]
    self._allow_all_external = False
    self._allow_external = set()
    self._allow_unverified = set()
    self._precedence = Sorter.DEFAULT_PACKAGE_PRECEDENCE
    self._context = Context.get()

  # TODO(wickman) Resolve duplicates here?
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
        [precedent for precedent in self._precedence if precedence is not WheelPackage])
    return self
  
  def allow_builds(self):
    if SourcePackage not in self._precedence:
      self._precedence = self._precedence + (SourcePackage,)
    return self

  def no_allow_builds(self):
    self._precedence = tuple(
        [precedent for precedent in self._precedence if precedence is not SourcePackage])
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
    )


class ResolverOptions(object):
  def __init__(self,
               fetchers=None,
               allow_all_external=False,
               allow_external=frozenset(),
               allow_unverified=frozenset(),
               precedence=None):
    self._fetchers = fetchers or [PyPIFetcher()]
    self._allow_all_external = allow_all_external
    self._allow_external = allow_external
    self._allow_unverified = allow_unverified
    self._precedence = precedence or Sorter.DEFAULT_PACKAGE_PRECEDENCE
    self._context = Context.get()  # XXX #58

  def get_context(self, key):
    return self._context

  def get_crawler(self, key):
    return Crawler(self.get_context(key))

  def get_sorter(self):
    return Sorter(self._precedence)

  def get_translator(self, interpreter, platform):
    translators = []
    
    # ugh
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
  class Error(Exception): pass

  @classmethod
  def filter_packages_by_interpreter(cls, packages, interpreter, platform):
    return [package for package in packages
        if package.compatible(interpreter.identity, platform)]

  def __init__(self,
               interpreter=None,
               platform=None,
               translator=None,
               options=None):
    self._interpreter = interpreter or PythonInterpreter.get()
    self._platform = platform or Platform.current()
    self._translator = translator or Translator.default(
        interpreter=self._interpreter,
        platform=self._platform,
    )
    self._options = options or ResolverOptions()

  def package_iterator(self, resolvable, existing=None):
    if existing:
      iterator = StaticIterator(existing)
    else:
      iterator = self._options.get_iterator(resolvable.name)
    existing = resolvable.packages(iterator)
    return self.filter_packages_by_interpreter(existing, self._interpreter, self._platform)

  def build(self, package):
    with TRACER.timed('Fetching %s' % package.url, V=2):
      context = self._options.get_context(package.name)
      local_package = Package.from_href(context.fetch(package))
    with TRACER.timed('Translating %s into distribution' % local_package.path, V=2):
      dist = self._translator.translate(local_package)
    if dist is None:
      raise Untranslateable('Package %s is not translateable by %s' % (
          package, self._translator))
    if not distribution_compatible(dist, self._interpreter, self._platform):
      raise Untranslateable('Could not get distribution for %s on appropriate platform.' %
          package)
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

    return distributions.values()


class CachingResolver(Resolver):
  class Error(Exception): pass

  @classmethod
  def filter_packages_by_ttl(cls, packages, ttl, now=None):
    now = now if now is not None else time.time()
    return [package for package in packages
        if package.remote or package.local and (now - os.path.getmtime(package.path)) < ttl]

  def __init__(self, cache, cache_ttl, *args, **kw):
    self.__cache = cache
    self.__cache_ttl = cache_ttl
    super(CachingResolver, self).__init__(*args, **kw)

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
    translator=None,
    interpreter=None,
    platform=None,
    context=None,      # XXX
    threads=1,         # XXX
    precedence=None,
    cache=None,
    cache_ttl=None):

  options = ResolverOptions(
      fetchers=fetchers,
      precedence=precedence,
  )

  keywords = dict(
      translator=translator,
      interpreter=interpreter,
      platform=platform,
      options=options,
  )

  if cache:
    resolver = CachingResolver(cache, cache_ttl, **keywords)
  else:
    resolver = Resolver(**keywords)

  return resolver.resolve(resolvables_from_iterable(requirements))
