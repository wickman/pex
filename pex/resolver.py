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


class StaticIterator(IteratorInterface):
  def __init__(self, packages):
    self._packages = packages
    
  def iter(self, req):
    for package in self._packages:
      if package.satisfies(req):
        yield package


# All the state carried along for resolution.
class ResolvableSet(object):
  class Error(Exception): pass
  class Unsatisfiable(Error): pass

  @classmethod
  def filter_packages_by_interpreter(cls, packages, interpreter, platform):
    pass
  
  @classmethod
  def filter_packages_by_ttl(cls, packages, ttl):
    pass

  def __init__(self, cache=None, cache_ttl=None):
    self.__resolvables = defaultdict(list)
    self.__packages = defaultdict(list)
    self.__distributions = {}
    self.__cache = cache
    self.__cache_ttl = cache_ttl
    self.__cache_iterator = Iterator(fetchers=[Fetcher([self.__cache])])

  def get_packages_cached(self, resolvable, interpreter, platform):
    cached_packages = resolvable.packages(self.__cache_iterator)
    cached_packages = self.filter_packages_by_interpreter(cached_packages, interpreter, platform)
      
    if cached_packages:
      if resolvable.exact:
        return cached_packages
        
      if self.__cache_ttl:
        cached_packages = self.filter_packages_by_ttl(cached_packages, self.__cache_ttl)
        if cached_packages:
          return cached_packages
    
    return []

  def add(self, resolvable, iterator, interpreter, platform):
    """Add a resolvable using a specific package iterator."""
    if resolvable in self.__resolvables[resolvable.name]:
      return
    
    if self.__packages[resolvable.name]:
      # there is an existing package set; constrain to it
      iterator = StaticIterator(self.__packages[resolvable.name])
    
    cached_packages = self.get_packages_cached(resolvable, interpreter, platform)
    if cached_packages:
      self.__packages[resolvable.name] = cached_packages
    else:
      self.__packages[resolvable.name] = self.filter_packages_by_interpreter(
          resolvable.packages(iterator), interpreter, platform)
    
    if not self.__packages[resolvable.name]:
      raise self.Unsatisfiable('Could not satisfy all requirements:\n%s' % '\n'.join(
          map(str, resolvable) for resolvable in self.__resolvables[resolvable.name]))
  
  def select(self):
    """Returns a mapping of name => best package for resolvables in this ResolvableSet."""
    return dict((name, packages[0]) for (name, packages) in self.__packages.items())

  def extras(self, name):
    return set.union(set(resolvable.extras) for resolvable in self.__resolvables[name])


# All the state carried along for resolution.
class ResolvableSet(object):
  class Error(Exception): pass
  class Unsatisfiable(Error): pass

  def __init__(self):
    self.__resolvables = defaultdict(set)
    self.__packages = defaultdict(list)

  def merge(self, resolvable, packages):
    """Add a resolvable using a specific package iterator."""
    self.__resolvables[resolvable.name].add(resolvable)
    self.__packages[resolvable.name] = sorted(
        set(packages).intersection(self.__packages[resolvable.name]))
    if not self.__packages[resolvable.name]:
      raise self.Unsatisfiable('Could not satisfy all requirements:\n%s' % '\n'.join(
          map(str, resolvable) for resolvable in self.__resolvables[resolvable.name]))
  
  def get(self, name):
    return list(self.__packages.get(name, []))  # make a copy
  
  def select(self):
    """Returns a mapping of name => best package for resolvables in this ResolvableSet."""
    return dict((name, packages[0]) for (name, packages) in self.__packages.items())

  def extras(self, name):
    return set.union(set(resolvable.extras) for resolvable in self.__resolvables[name])


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
        allow_external=frozenset(self._allow_external),
        allow_all_external=self._allow_all_external,
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
  
  @classmethod
  def filter_packages_by_ttl(cls, packages, ttl, now=None):
    now = now if now is not None else time.time()
    return [package for package in packages
        if package.remote or package.local and (now - os.path.getmtime(package.path)) < ttl]

  def __init__(self,
               interpreter=None,
               platform=None,
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
   *context=None,
      | --allow-insecure
      | --allow-unverified
    threads=1,
    precedence=None,
      | --no-use-wheel
    cache=None,        | pex only
    cache_ttl=None     | pex only
    prerelease=False   | pex only --pre

   *crawler
      | --allow-external
      | --allow-all-external

    -----------

    cache=True ==>
      fetchers updated
      iterator chained
    """
    self.__cache = cache
    self.__cache_ttl = cache_ttl
    
    #--
    self._interpreter = interpreter or PythonInterpreter.get()
    self._platform = platform or Platform.current()
    self._translator = translator or Translator.default(interpreter=interpreter, platform=platform)
    self._options = options or ResolverOptions.default()
    
    #--
    self.__distributions = {}

  def __package_iterator(self, resolvable, existing=None):
    if existing:
      iterator = StaticIterator(existing)
    else:
      iterator = self._options.get_iterator(resolvable.name)

    existing = resolvable.packages(iterator)

    return self.filter_packages_by_interpreter(existing, self._interpreter, self._platform)

  def __package_iterator_cached(self, resolvable, existing=None):
    iterator = Iterator(fetchers=Fetcher([self.__cache]))
    packages = resolvable.packages(iterator)

    if packages:
      if resolvable.exact:
        return packages
      
      if self.__cache_ttl:
        packages = self.filter_packages_by_ttl(packages, self.__cache_ttl)
        if packages:
          return packages

    return self.__package_iterator(resolvable, existing=existing)

  def build(self, package):
    if package not in self._distributions:
      with TRACER.timed('Fetching %s' % package.url, V=2):
        context = self._options.get_context()
        local_package = Package.from_href(context.fetch(package, into=self.__cache))
      if package.remote:
        # this was a remote resolution -- so if we copy from remote to local but the
        # local already existed, update the mtime of the local so that it is correct
        # with respect to cache_ttl.
        os.utime(local_package.path, None)
      with TRACER.timed('Translating %s into distribution' % local_package.path, V=2):
        dist = self._translator.translate(local_package, into=self.__cache)
      if dist is None:
        raise Untranslateable('Package %s is not translateable.' % package)
      if not distribution_compatible(dist, self._interpreter, self._platform):
        raise Untranslateable('Could not get distribution for %s on appropriate platform.' %
            package)
      self._distributions[package] = dist
    return self._distributions[package]
  
  def requires(self, package, extras):
    if package not in self._distributions:
      with TRACER.timed('Fetching %s' % package.url, V=2):
        context = self._options.get_context()
        local_package = Package.from_href(context.fetch(package, into=self.__cache))
      if package.remote:
        # this was a remote resolution -- so if we copy from remote to local but the
        # local already existed, update the mtime of the local so that it is correct
        # with respect to cache_ttl.
        os.utime(local_package.path, None)
      with TRACER.timed('Translating %s into distribution' % local_package.path, V=2):
        dist = self._translator.translate(local_package, into=self.__cache)
      if dist is None:
        raise Untranslateable('Package %s is not translateable.' % package)
      if not distribution_compatible(dist, self._interpreter, self._platform):
        raise Untranslateable('Could not get distribution for %s on appropriate platform.' %
            package)
      self._distributions[package] = dist
    return [ResolvableRequirement(req) for req
            in self._distributions[package].requires(extras=extras)]

  def resolve(self, resolvables, requirement_set=None):
    resolvable_set = resolvable_set or ResolvableSet()
    processed_resolvables = set()
    processed_packages = {}
    distributions = []
    
    while resolvables:
      while resolvables:
        resolvable = resolvables.pop(0)
        if resolvable in processed_resolvables:
          continue
        existing = resolvable_set.get(resolvable.name)
        packages = self.__package_iterator_cached(resolvable, existing=existing)
        resolvable_set.merge(resolvable, packages)
        processed_resolvables.add(resolvable)

      for resolvable_name, package in resolvable_set.select().items():
        if resolvable_name in processed_packages:
          if package != processed_packages[resolvable_name]:
            raise self.Error('Ambiguous resolvable: %s' % resolvable_name)
          continue
        distribution = self.build(package)
        resolvables.extend(ResolvableRequirement(req) for req in
            distribution.requires(extras=resolvable_set.extras(resolvable_name)))
        distributions.append(distribution)

    return distributions


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

  resolver = Resolver(
      translator=translator,
      interpreter=interpreter,
      platform=platform,
      context=context,
      #threads=threads,
      #precedence=precedence,
      #cache=cache,
      #cache_ttl=cache_ttl,
      options=ResolverOptions.default())

  resolvables = [ResolvableRequirement.from_string(req) for req in requirements]
  return resolver.resolve(resolvables)


# resolvable_set
#   name => requirement version(s)
#   name => packages
#
# resolvable:
#    https://../foo-2.0.3.tar.gz
#    git://asdfasdf/#egg=MyThing
#    Flask>=3.2
#    .
#
# any of which can take a [extra1,extra2,...] at the end
#
# .as_requirement
# for local path would require packaging first (sdist)
# 
# so we just need .as_requirement
# to do so for vcs/unpackaged local paths, we need to [clone+]package
#
# resolvable1,...,resolvableN
#
# resolvable1 [name1] => [package1_1, ..., package1_N]
# resolvable2 [name2] => [package2_1]
# resolvable3 [name3] => [package3_1, ..., package3_N]
#
# name1 => resolvable1 => []
# name2 => resolvable2 => []
# name3 => resolvable3 resolvable4 => [] 
#
# process each resolvable
#
# name1 => resolvable1* => [package1_1, ..., package1_N]
# name2 => resolvable2* => [package2_1]
# name3 => resolvable3* resolvable4* => [package3_1, package3_2, package3_3]
#
# select top packages, which produce more resolvables:
#
# name1 => resolvable1* resolvable5 => [package1_1*, ..., package1_N]
# name2 => resolvable2* => [package2_1*]
# name3 => resolvable3* resolvable4* => [package3_1*, package3_2, package3_3] 
# name4 => resolvable6 => []
# name5 => resolvable7 => []
#
# process each new resolvable
#
# until no more new resolvables.
