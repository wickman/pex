# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod, abstractproperty
from collections import Iterable

from pkg_resources import Requirement, safe_name

from .compatibility import AbstractClass, string as compatibility_string
from .iterator import Iterator
from .fetcher import Fetcher, PyPIFetcher
from .package import Package


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
