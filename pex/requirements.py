# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod, abstractproperty
from collections import Iterable

from pkg_resources import Requirement, safe_name

from .compatibility import AbstractClass, string as compatibility_string
from .iterator import Iterator
from .fetcher import Fetcher, PyPIFetcher
from .package import Package


def maybe_requirement(req):
  if isinstance(req, Requirement) or quacks_like_req(req):
    return req
  elif isinstance(req, compatibility_string):
    return Requirement.parse(req)
  raise ValueError('Unknown requirement %r' % (req,))


def maybe_requirement_list(reqs):
  if isinstance(reqs, (compatibility_string, Requirement)) or quacks_like_req(reqs):
    return [maybe_requirement(reqs)]
  elif isinstance(reqs, Iterable):
    return [maybe_requirement(req) for req in reqs]
  raise ValueError('Unknown requirement list %r' % (reqs,))


def requirement_is_exact(req):
  return req.specs and len(req.specs) == 1 and req.specs[0][0] == '=='


class Resolvable(AbstractClass):
  """An entity that can be resolved into a package."""

  class Error(Exception): pass
  class InvalidRequirement(Error): pass

  _REGISTRY = []

  @classmethod
  def register(cls, implementation):
    cls._REGISTRY.append(implementation)

  @classmethod
  def get(cls, resolvable_string):
    """Get a :class:`Resolvable` from a string.

    :returns: A :class:`Resolvable` or ``None`` if no implementation was appropriate.
    """
    for resolvable_impl in cls._REGISTRY:
      try:
        return resolvable_impl.from_string(resolvable_string)
      except cls.InvalidRequirement:
        continue

  # @abstractmethod - Only available in Python 3.3+
  @classmethod
  def from_string(cls, requirement_string):
    """Produce a resolvable from this requirement string.

    :returns: Instance of the particular Resolvable implementation.
    :raises InvalidRequirement: If requirement_string is not a valid string representation
      of the resolvable.
    """
    raise cls.InvalidRequirement('Resolvable is abstract.')

  @abstractmethod
  def packages(self, finder):
    """Given a finder of type :class:`Iterable` (possibly ignored), resolve packages.

    :returns: An iterable of compatible :class:`Package` objects.
    """

  @abstractproperty
  def name(self):
    pass


class ResolvableRepository(Resolvable):
  # A 'git+', 'svn+', 'hg+', 'bzr+' project.  Not supported.

  COMPATIBLE_VCS = frozenset(['git', 'svn', 'hg', 'bzr'])

  @classmethod
  def from_string(cls, requirement_string):
    if any(requirement_string.startswith('%s+' % vcs) for vcs in cls.COMPATIBLE_VCS):
      # further delegate
      pass

    raise cls.InvalidRequirement('Versioning system URLs not supported.')

  def packages(self, finder):
    return []

  @property
  def name(self):
    raise NotImplemented


class ResolvablePackage(Resolvable):
  # A Package (either local or remote)
  @classmethod
  def from_string(cls, requirement_string):
    package = Package.from_href(requirement_string)
    if package is None:
      raise cls.InvalidRequirement('Requirement string does not appear to be a package.')
    return cls(package)

  def __init__(self, package):
    self.package = package

  def packages(self, finder):
    return self.package

  @property
  def name(self):
    return self.package.name


class ResolvableRequirement(Resolvable):
  # A Requirement wrapper
  @classmethod
  def from_string(cls, requirement_string):
    try:
      return cls(Requirement.parse(requirement_string))
    except ValueError:
      raise cls.InvalidRequirement('%s does not appear to be a requirement string.' % requirement_string)

  def __init__(self, requirement, follow_links=False, iterator=None):
    self.requirement = requirement
    self._follow_links = follow_links
    self._iterator = iterator

  def __eq__(self, other):
    return isinstance(other, ResolvableRequirement) and (
       self.requirement == other.requirement and
       self._follow_links == other._follow_links)

  @property
  def iterator(self):
    return self._iterator

  def clone_from(self, follow_links=False, iterator=None):
    return ResolvableRequirement(
        self.requirement,
        follow_links=follow_links,
        iterator=self.iterator or iterator)

  def packages(self, finder):
    iterator = self._iterator or finder
    return [package for package in iterator.iter(self.requirement, follow_links=self._follow_links)
        if package.satisfies(requirement)]

  @property
  def name(self):
    return self.requirement.key


Resolvable.register(ResolvableRepository)
Resolvable.register(ResolvablePackage)
Resolvable.register(ResolvableRequirement)


# The abstractions here are pretty messy :-\
class RequirementsTxt(object):
  class Error(Exception): pass
  class UnsupportedLine(Error): pass
  class UnsupportedObject(Error): pass

  @classmethod
  def _startswith_any(cls, line, things):
    return any(line.startswith(thing) for thing in things)

  @classmethod
  def _get_parameter(cls, line):
    sline = line.split('=')
    if len(sline) != 2:
      sline = line.split()
    if len(sline) != 2:
      raise cls.UnsupportedLine('Unrecognized line format: %s' % line)
    return sline[1]

  @classmethod
  def _process_one_line(cls, requirements, line):
    line = line.strip()
    if not line or line.startswith('#'):
      return
    elif line.startswith('-e '):
      raise cls.UnsupportedLine('Editable distributions not supported: %s' % line)
    elif cls._startswith_any(line, ('-i ', '--index-url', '--extra-index-url')):
      requirements.add_index(cls._get_parameter(line))
      return
    elif cls._startswith_any(line, ('-f ', '--find-links')):
      requirements.add_repo(cls._get_parameter(line))
      return
    elif line.startswith('--allow-external'):
      requirements.allow_external(cls._get_parameter(line))
      return
    elif line.startswith('--allow-all-external'):
      requirements.allow_all_external()
      return
    elif line.startswith('--allow-unverified'):
      TRACER.log('--allow-unverified is ignored by PEX.')
      return
    elif line.startswith('--no-index'):
      requirements.clear_indices()
      return
    elif cls._startswith_any(line, ('-r ', '--requirement')):
      # TODO(wickman) Should this be relativized?
      cls.from_file(cls._get_parameter(line), requirements=requirements)
      return
    else:
      requirements.add(Resolvable.get(line))

  @classmethod
  def from_lines(cls, lines, requirements=None):
    requirements = requirements or cls()
    for line in lines:
      cls._process_one_line(requirements, line)
    return requirements

  @classmethod
  def from_file(cls, filename, requirements=None):
    with open(filename, 'r') as fp:
      return cls.from_lines(fp.readlines(), requirements=requirements)

  @classmethod
  def from_iterable(cls, iterable, requirements=None):
    def iterate():
      for obj in iterable:
        if isinstance(obj, Resolvable):
          yield obj
        elif isinstance(obj, Requirement):
          yield ResolvableRequirement(obj)
        elif isinstance(obj, Package):
          yield ResolvablePackage(obj)
        elif isinstance(obj, compatibility_string):
          yield Resolvable.get(obj)
        else:
          raise cls.UnsupportedObject('Do not know how to resolve %s' % type(obj))
    requirements = requirements or cls()
    for resolvable in iterate():
      requirements.add(resolvable)
    return requirements

  def __init__(self):
    self._resolvables = []
    self._fetchers = [PyPIFetcher()]
    self._allow_all_external = False
    self._allow_external = set()

  def add(self, resolvable):
    self._resolvables.append(resolvable)

  def add_index(self, index):
    self._fetchers.append(PyPIFetcher(index))

  def add_repo(self, repo):
    self._fetchers.append(Fetcher([repo]))

  def clear_indices(self):
    self._fetchers = [fetcher for fetcher in self._fetchers if not isinstance(fetcher, PyPIFetcher)]

  def allow_all_external(self):
    self._allow_all_external = True

  def allow_external(self, name):
    self._allow_external.add(safe_name(name).lower())

  def iter(self, crawler=None, precedence=None):
    # Is this a leak?
    iterator = Iterator(fetchers=self._fetchers, crawler=crawler, precedence=precedence)

    for resolvable in self._resolvables:
      if isinstance(resolvable, ResolvableRequirement):
        # ick
        follow_links = self._allow_all_external or (
            safe_name(resolvable.name).lower() in self._allow_external)
        yield resolvable.clone_from(follow_links=follow_links, iterator=iterator)
      else:
        yield resolvable
