# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import shutil
import time
from collections import defaultdict
from functools import partial

from pkg_resources import Distribution

from .base import maybe_requirement_list, requirement_is_exact
from .crawler import Crawler
from .fetcher import Fetcher, PyPIFetcher
from .http import Context
from .interpreter import PythonInterpreter
from .iterator import Iterator, IteratorInterface
from .orderedset import OrderedSet
from .package import Package, distribution_compatible
from .platforms import Platform
from .resolvable import ResolvableRequirement
from .tracer import TRACER
from .translator import Translator


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
      self.__packages[resolvable.name] = sorted(
          set(packages).intersection(self.__packages[resolvable.name]))
    else:
      self.__packages[resolvable.name] = sorted(packages)
    if not self.__packages[resolvable.name]:
      raise self.Unsatisfiable('Could not satisfy all requirements:\n%s' % '\n'.join(
          map(str, self.__resolvables[resolvable.name])))
  
  def get(self, name):
    return list(self.__packages.get(name, []))  # make a copy
  
  def select(self):
    """Returns a mapping of name => best package for resolvables in this ResolvableSet."""
    return dict((name, packages[0]) for (name, packages) in self.__packages.items())

  def extras(self, name):
    return set.union(*[set(resolvable.extras()) for resolvable in self.__resolvables[name]])


class ResolverOptions(object):
  @classmethod
  def from_requirements_txt(cls, requirements_txt):
    raise NotImplemented
  
  @classmethod
  def default(cls):
    default = cls()
    default.add_index(PyPIFetcher.PYPI_BASE)
    return default

  def __init__(self):
    self._fetchers = []
    self._allow_all_external = False
    self._allow_external = set()
    self._allow_unverified = set()
    self._precedence = Iterator.DEFAULT_PACKAGE_PRECEDENCE
    self._context = Context.get()

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
  
  def no_use_wheel(self):
    self._precedence = (EggPackage, SourcePackage)
  
  # --
  def set_context(self, context):
    self._context = context
  
  def set_precedence(self, precedence):
    self._precedence = precedence
  
  # ---
  def get_context(self, key):
    return self._context

  def get_crawler(self, key):
    return Crawler(self.get_context(key))

  def get_iterator(self, key):
    return Iterator(
        fetchers=self._fetchers,
        crawler=self.get_crawler(key),
        precedence=self._precedence,
        #allow_external=frozenset(self._allow_external),
        #allow_all_external=self._allow_all_external,
    )


class Resolver(object):
  class Error(Exception): pass
  
  @classmethod
  def from_requirements(cls, requirements_txt):
    rtxt = RequirementsTxt.from_file(requirements_txt)
    return cls(
    )

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
    self._translator = translator or Translator.default(interpreter=interpreter, platform=platform)
    self._options = options or ResolverOptions.default()

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
      raise Untranslateable('Package %s is not translateable.' % package)
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
    
    while resolvables:
      while resolvables:
        resolvable = resolvables.pop(0)
        if resolvable in processed_resolvables:
          continue
        existing = resolvable_set.get(resolvable.name)
        packages = self.package_iterator(resolvable, existing=existing)
        resolvable_set.merge(resolvable, packages)
        processed_resolvables.add(resolvable)

      for resolvable_name, package in resolvable_set.select().items():
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
    iterator = Iterator(fetchers=[Fetcher([self.__cache])])
    packages = resolvable.packages(iterator)

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
    return dist


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

  options = ResolverOptions()
  if context:
    options.set_context(context)
  if precedence:
    options.set_precedence(precedence)
  
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

  return resolver.resolve(requirements)
