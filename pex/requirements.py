# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

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


# Process lines in the requirements.txt format as defined here:
# https://pip.pypa.io/en/latest/reference/pip_install.html#requirements-file-format
def _process_one_line(builder, line, relpath):
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
  elif line.startswith('--no-use-wheel'):
    builder.no_use_wheel()
  elif _startswith_any(line, ('-r ', '--requirement')):
    path = os.path.join(relpath, _get_parameter(line))
    resolvables, builder = requirements_from_file(path, builder)
  else:
    try:
      resolvables.append(Resolvable.get(line))
    except Resolvable.InvalidRequirement:
      raise UnsupportedLine('Unsupported requirements.txt option: %s' % line)
  return resolvables


def requirements_from_lines(lines, builder=None, relpath=None):
  relpath = relpath or os.getcwd()
  builder = builder or ResolverOptionsBuilder()
  resolvables = []
  for line in lines:
    resolvables.extend(_process_one_line(builder, line, relpath))
  return resolvables, builder


def requirements_from_file(filename, builder=None):
  relpath = os.path.dirname(filename)
  with open(filename, 'r') as fp:
    return requirements_from_lines(fp.readlines(), builder=builder, relpath=relpath)
