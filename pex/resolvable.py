from .base import maybe_requirement, requirement_is_exact
from .compatibility import AbstractClass, string as compatibility_string
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

  @property
  def exact(self):
    return True


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

  @property
  def exact(self):
    return True


class ResolvableRequirement(Resolvable):
  # A Requirement wrapper
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


Resolvable.register(ResolvableRepository)
Resolvable.register(ResolvablePackage)
Resolvable.register(ResolvableRequirement)
