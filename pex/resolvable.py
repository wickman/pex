# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod, abstractproperty

from pkg_resources import Requirement

from .base import maybe_requirement, requirement_is_exact
from .compatibility import string as compatibility_string
from .compatibility import AbstractClass
from .package import Package


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
    raise cls.InvalidRequirement('Unknown requirement type: %s' % resolvable_string)

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

  @abstractproperty
  def exact(self):
    pass

  @abstractmethod
  def extras(self, interpreter=None):
    pass


class ResolvableRepository(Resolvable):
  """A VCS repository resolvable, e.g. 'git+', 'svn+', 'hg+', 'bzr+' packages."""

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

  @property
  def exact(self):
    return True


class ResolvablePackage(Resolvable):
  """A package (.tar.gz, .egg, .whl, etc) resolvable."""

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

  @property
  def exact(self):
    return True

  def __hash__(self):
    return hash(self.package)

  def __str__(self):
    return str(self.package)


class ResolvableRequirement(Resolvable):
  """A requirement (e.g. 'setuptools', 'Flask>=0.8,<0.9', 'pex[whl]')."""

  @classmethod
  def from_string(cls, requirement_string):
    try:
      return cls(maybe_requirement(requirement_string))
    except ValueError:
      raise cls.InvalidRequirement('%s does not appear to be a requirement string.' %
          requirement_string)

  def __init__(self, requirement):
    self.requirement = requirement

  def __eq__(self, other):
    return isinstance(other, ResolvableRequirement) and self.requirement == other.requirement

  def packages(self, finder):
    return list(finder.iter(self.requirement))

  @property
  def name(self):
    return self.requirement.key

  @property
  def exact(self):
    return requirement_is_exact(self.requirement)

  def extras(self, interpreter=None):
    return self.requirement.extras

  def __hash__(self):
    return hash(self.requirement)

  def __str__(self):
    return str(self.requirement)


Resolvable.register(ResolvableRepository)
Resolvable.register(ResolvablePackage)
Resolvable.register(ResolvableRequirement)


# TODO(wickman) maybe have Resolvable.from_concrete and delegate to that.
def resolvables_from_iterable(iterable):
  """Given an iterable of resolvable-like objects, return list of Resolvable objects.

  :param iterable: An iterable of :class:`Resolvable`, :class:`Requirement`, :class:`Package`,
      or `str` to map into an iterable of :class:`Resolvable` objects.
  :returns: A list of :class:`Resolvable` objects.
  """

  def translate(obj):
    if isinstance(obj, Resolvable):
      return obj
    elif isinstance(obj, Requirement):
      return ResolvableRequirement(obj)
    elif isinstance(obj, Package):
      return ResolvablePackage(obj)
    elif isinstance(obj, compatibility_string):
      return Resolvable.get(obj)
    else:
      raise ValueError('Do not know how to resolve %s' % type(obj))
  return list(map(translate, iterable))
