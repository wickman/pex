# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from .resolvable import Resolvable
from .resolver import ResolverOptionsBuilder


class UnsupportedLine(Exception):
  pass


def _startswith_any(line, things):
  return any(line.startswith(thing) for thing in things)


def _get_parameter(line):
  sline = line.split('=')
  if len(sline) != 2:
    sline = line.split()
  if len(sline) != 2:
    raise UnsupportedLine('Unrecognized line format: %s' % line)
  return sline[1]


def _process_one_line(builder, line):
  line = line.strip()
  resolvables = []
  if not line or line.startswith('#'):
    return resolvables
  elif line.startswith('-e '):
    raise UnsupportedLine('Editable distributions not supported: %s' % line)
  elif _startswith_any(line, ('-i ', '--index-url')):
    builder.set_index(_get_parameter(line))
  elif line.startswith('--extra-index-url'):
    builder.add_index(_get_parameter(line))
  elif _startswith_any(line, ('-f ', '--find-links')):
    builder.add_repository(_get_parameter(line))
  elif line.startswith('--allow-external'):
    builder.allow_external(_get_parameter(line))
  elif line.startswith('--allow-all-external'):
    builder.allow_all_external()
  elif line.startswith('--allow-unverified'):
    builder.allow_unverified(_get_parameter(line))
  elif line.startswith('--no-index'):
    builder.clear_indices()
  elif _startswith_any(line, ('-r ', '--requirement')):
    # TODO(wickman) Should this be relativized?
    resolvables, builder = requirements_from_file(_get_parameter(line), builder)
  else:
    resolvables.append(Resolvable.get(line))
  return resolvables


def requirements_from_lines(lines, builder=None):
  builder = builder or ResolverOptionsBuilder()
  resolvables = []
  for line in lines:
    resolvables.extend(_process_one_line(builder, line))
  return resolvables, builder


def requirements_from_file(filename, builder=None):
  with open(filename, 'r') as fp:
    return requirements_from_lines(fp.readlines(), builder=builder)


"""
@classmethod
def from_iterable(cls, iterable, builder=None):
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
        raise UnsupportedObject('Do not know how to resolve %s' % type(obj))
  requirements = requirements or cls()
  for resolvable in iterate():
    requirements.add(resolvable)
  return requirements
"""
