# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""
Extract and evaluate PEP426 environment markers.

For more information about environment markers, see:
https://www.python.org/dev/peps/pep-0426/#environment-markers
"""

import os
import platform
import sys
from collections import namedtuple


def format_full_version(info):
  version = '{0.major}.{0.minor}.{0.micro}'.format(info)
  kind = info.releaselevel
  if kind != 'final':
    version += kind[0] + str(info.serial)
  return version


PEP426_EXPRS = (
    ('python_version', lambda: '{0.major}.{0.minor}'.format(sys.version_info)),
    ('python_full_version', lambda: format_full_version(sys.version_info)),
    ('os_name', lambda: os.name),
    ('sys_platform', lambda: sys.platform),
    ('platform_release', lambda: platform.release()),
    ('platform_version', lambda: platform.version()),
    ('platform_machine', lambda: platform.machine()),
    ('platform_python_implementation', lambda: platform.python_implementation()),
    ('implementation_name', lambda: sys.implementation.name),
    ('implementation_version', lambda: format_full_version(sys.implementation.version)),
)


class PEP426Marker(namedtuple('PEP426Marker', [name for name, _ in PEP426_EXPRS])):
  @classmethod
  def from_kwargs(cls, **markers):
    empty_markers = dict((expr_name, '') for expr_name, _ in PEP426_EXPRS)
    empty_markers.update(markers)
    return cls(**empty_markers)

  @classmethod
  def from_lines(cls, lines):
    markers = {}
    for line in lines:
      try:
        expr_name, expr_value = line.split(':', 1)
      except ValueError:
        # This shouldn't happen but we cannot fail hard.
        continue
      markers[expr_name] = expr_value
    return cls.from_kwargs(**markers)


parse_marker = PEP426Marker.from_lines


class Token(object):
  OPERATORS = ('not in', 'in', '==', '!=', '<=', '>=', '<', '>')
  OTHER = ('(', ')', 'and', 'or')

  # Sort tokens by length.
  ALL = tuple(reversed(sorted(OPERATORS + OTHER, key=lambda token: len(token))))

  def __init__(self, value):
    if value not in self.ALL:
      raise ValueError('Unknown token %r' % value)
    self.value = value

  def is_operator(self):
    return self.value in self.OPERATORS

  def __eq__(self, other):
    return isinstance(other, Token) and self.value == other.value

  def __ne__(self, other):
    return not isinstance(other, Token) or self.value != other.value

  def __str__(self):
    return self.value

  def __repr__(self):
    return 'Token(%r)' % self.value


class String(object):
  def __init__(self, value):
    self.value = value

  def __eq__(self, other):
    return isinstance(other, String) and self.value == other.value

  def __str__(self):
    return repr(self.value)


def tokenize(marker, string):
  def get_subexpr():
    for subexpr, _ in PEP426_EXPRS:
      if string.startswith(subexpr):
        return subexpr

  while string:
    if string.startswith(' '):
      string = string[1:]
      continue

    subexpr = get_subexpr()
    if subexpr:
      yield String(getattr(marker, subexpr, ''))
      string = string[len(subexpr):]
      continue

    # PEP426 specifies only ' but " is found everywhere, so we have to honor it.
    if string.startswith("'") or string.startswith('"'):
      starting_quote = string[0]
      closing_quote = string.find(string[0], 1)
      if closing_quote == -1:
        raise ValueError
      yield String(string[1:closing_quote])
      string = string[closing_quote + 1:]
      continue

    for substr in Token.ALL:
      if string.startswith(substr):
        yield Token(substr)
        string = string[len(substr):]
        break
    else:
      raise ValueError


def _reduce_statements(statements):
  # Given a stream of True/False <or/and> True/False <or/and> ... reduce to a truth
  # value while honoring and/or operator precedence.
  for k in reversed(range(len(statements))):
    if statements[k] == Token('and'):
      statements[k - 1:k + 2] = [statements[k - 1] and statements[k + 1]]
  return any(statements[::2])


def _split_statements(tokens):
  # Split tokens into a stream of True/False <operator> True/False <operator> ...
  offset = 0
  statements = []

  while True:
    value, consumed = eval_expr(tokens[offset:])
    offset += consumed

    statements.append(bool(value))

    if len(tokens) == offset:
      # done
      break

    elif len(tokens) < offset:
      # not possible
      raise ValueError

    # multiple expr
    if tokens[offset] in (Token('and'), Token('or')):
      statements.append(tokens[offset])
      offset += 1
    else:
      # Must be an RPAREN?
      break

  return statements, offset


def eval_marker(tokens):
  statements, offset = _split_statements(tokens)
  return _reduce_statements(statements), offset


def eval_expr(tokens):
  if isinstance(tokens[0], Token):
    if tokens[0] == Token('('):
      value, offset = eval_marker(tokens[1:])
      if tokens[offset + 1] != Token(')'):
        raise ValueError('Expected LPAREN to be matched by RPAREN, got %r' % tokens[offset + 1])
      return value, offset + 2
    else:
      raise ValueError("Expression must start with '(' or String.")
  else:
    return eval_subexpr(tokens)


def eval_subexpr(tokens):
  expr0 = tokens[0]
  if not isinstance(expr0, String):
    raise ValueError
  expr0value = expr0.value

  if len(tokens) == 1 or not tokens[1].is_operator():
    return bool(expr0value), 1

  operator = tokens[1]

  if len(tokens) < 3:
    raise ValueError('Unexpected end of token stream.')

  expr1 = tokens[2]
  if not isinstance(expr1, String):
    raise ValueError
  expr1value = expr1.value

  return eval_subexpr_op(expr0value, operator, expr1value), 3


def eval_subexpr_op(subexpr0, operator, subexpr1):
  if operator == Token('=='):
    return subexpr0 == subexpr1
  elif operator == Token('!='):
    return subexpr0 != subexpr1
  elif operator == Token('<='):
    return subexpr0 <= subexpr1
  elif operator == Token('>='):
    return subexpr0 >= subexpr1
  elif operator == Token('>'):
    return subexpr0 > subexpr1
  elif operator == Token('<'):
    return subexpr0 < subexpr1
  elif operator == Token('in'):
    return subexpr0 in subexpr1
  elif operator == Token('not in'):
    return subexpr0 not in subexpr1
  raise ValueError


def evaluate(marker, expression):
  """Given a PEP426 environment marker and a constraint expression, return its truth value.

  :param marker: A :class:`PEP426Marker` environment marker to use to evaluate the expression.
  :param expression: An expression in the form of a string, e.g. "'linux' in sys_platform" or
      "python_version == '2.6' or python_version == '2.7'".
  """

  # an alternative to implementing all the eval_* stuff is just
  #
  #     return eval(' '.join(map(str, tokenize(marker, expression))))
  #
  # this would rely upon the python intepreter to do the evaluation, which may or may not be
  # desirable depending upon your tolerance for risk/security vuln/whatever.
  token_stream = list(tokenize(marker, expression))
  value, _ = eval_marker(token_stream)
  return value


def __iter_marker_kv():
  for key, expr in PEP426_EXPRS:
    try:
      value = expr()
    except:  # noqa -- we must make this as safe as possible
      continue
    yield key, value


def get_marker():
  return PEP426Marker.from_kwargs(**dict(__iter_marker_kv()))


if __name__ == '__main__':
  for key, val in __iter_marker_kv():
    print('%s:%s' % (key, val))
