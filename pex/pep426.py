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


PEP426Marker = namedtuple(
    'PEP426Marker',
    [name for name, _ in PEP426_EXPRS]
)


def parse_marker(lines):
  markers = dict((expr_name, '') for expr_name in PEP426_EXPRS)

  for line in lines:
    expr_name, expr_value = line.split(':', 1)
    markers[expr_name] = expr_value

  return PEP426Marker(**markers)


class Token(object):
  LPAREN  = 0
  RPAREN  = 1
  EQ      = 2
  NEQ     = 3
  LT      = 4
  GT      = 5
  LEQ     = 6
  GEQ     = 7
  IN      = 8
  NOTIN   = 9
  AND     = 10
  OR      = 11
  SUBEXPR = 12
  STRING  = 13

  def __init__(self, type, value=None):
    self.type = type
    self.value = value


OTHER_TOKENS = (
  ('(', Token.LPAREN),
  (')', Token.RPAREN),
  ('and', Token.AND),
  ('or', Token.OR),
)


OPERATOR_TOKENS = (
  ('==', Token.EQ),
  ('!=', Token.NEQ),
  ('<=', Token.LEQ),
  ('>=', Token.GEQ),
  ('>', Token.GT),
  ('<', Token.LT),
  ('in', Token.IN),
  ('not in', Token.NOTIN),
)


OPERATORS = frozenset(op[1] for op in OPERATOR_TOKENS)


def tokenize(string):
  offset = 0

  def lookahead(substr):
    if string[offset:].startswith(substr):
      string = string[offset + len(substr):]
      return True

  def get_subexpr():
    for subexpr in SUBEXPRESSION_NAMES:
      if string.startswith(subexpr):
        return subexpr

  while string:
    if string.startswith(' '):
      string = string[1:]
      continue

    subexpr = get_subexpr()
    if subexpr:
      yield Token(Token.SUBEXPR, subexpr)
      string = string[len(subexpr):]
      continue

    if string.startswith("'"):
      closing_quote = string.find("'", 1)
      if closing_quote == -1:
        raise ValueError
      yield Token(Token.STRING, string[1:closing_quote])
      string = string[closing_quote + 1:]
      continue

    for substr, token in OTHER_TOKENS + OPERATOR_TOKENS:
      if string.startswith(substr):
        yield Token(token)
        string = string[len(substr):]
        break
    else:
      raise ValueError


def eval_marker(tag, tokens):
  offset = 0
  values = []
  operators = []

  while True:
    value, consumed = eval_expr(tag, tokens[offset:])
    offset += consumed

    values.append(value)

    if len(tokens) == offset:
      # done
      break
    elif len(tokens) < offset:
      # not possible
      raise ValueError

    # multiple expr
    if tokens[offset].type in (Token.AND, Token.OR):
      operators.append(tokens[offset])
      offset += 1
    else:
      break  # ?

  # evaluate
  aggregator = values.pop(0)

  while values:
    value1 = values.pop(0)
    operator = operators.pop()

    if operator.type == Token.AND:
      aggregator = aggregator and value1
    elif operator.type == Token.OR:
      aggregator = aggregator or value1
    else:
      raise ValueError

  return aggregator, offset


def eval_expr(tag, tokens):
  if tokens[0].type == Token.LPAREN:
    value, offset = eval_marker(tag, tokens[1:])
    if tokens[offset + 1].type != Token.RPAREN:
      raise ValueError('Expected LPAREN to be matched by RPAREN, got %r' % tokens[offset + 1])
    return value, offset + 2
  else:
    return eval_subexpr(tag, tokens)


def subexpr_value(tag, subexpr):
  if subexpr.type == Token.SUBEXPR:
    return getattr(tag, subexpr.value)
  elif subexpr.type == Token.STRING:
    return subexpr.value
  else:
    raise ValueError('subexpr_value expected a SUBEXPR or STRING, got type=%r' % subexpr.type)


def eval_subexpr(tag, tokens):
  expr0 = tokens[0]
  expr0value = subexpr_value(tag, expr0)

  if len(tokens) == 1 or tokens[1].type not in OPERATORS:
    return bool(expr0value), 1

  operator = tokens[1].type

  if len(tokens) < 3:
    raise ValueError('Unexpected end of token stream.')

  expr1 = tokens[2]
  expr1value = subexpr_value(tag, expr1)

  return eval_subexpr_op(expr0value, operator, expr1value), 3


def eval_subexpr_op(subexpr0, operator, subexpr1):
  if operator == Token.EQ:
    return subexpr0 == subexpr1
  elif operator == Token.NEQ:
    return subexpr0 != subexpr1
  elif operator == Token.LEQ:
    return subexpr0 <= subexpr1
  elif operator == Token.GEQ:
    return subexpr0 >= subexpr1
  elif operator == Token.GT:
    return subexpr0 > subexpr1
  elif operator == Token.LT:
    return subexpr0 < subexpr1
  elif operator == Token.IN:
    return subexpr0 in subexpr1
  elif operator == Token.NOTIN:
    return subexpr0 not in subexpr1
  raise ValueError


def evaluate(marker, expression):
  """Given a PEP426 environment marker and a constraint expression, return its truth value.

  :param marker: A :class:`PEP426Marker` environment marker to use to evaluate the expression.
  :param expression: An expression in the form of a string, e.g. "'linux' in sys_platform" or
      "python_version == '2.6' or python_version == '2.7'".
  """

  token_stream = list(tokenize(expression))
  value, _ = eval_marker(token_stream)
  return value


if __name__ == '__main__':
  for key, expr in PEP426_EXPRS:
    try:
      value = expr()
    except:
      continue
    print('%s:%s' % (key, value))
