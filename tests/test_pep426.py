import textwrap

from pex.pep426 import (
    PEP426Marker,
    get_marker,
    evaluate,
    tokenize,
)


PyPy24 = PEP426Marker.from_lines(textwrap.dedent("""
    python_version:2.7
    python_full_version:2.7.8
    os_name:posix
    sys_platform:darwin
    platform_release:13.4.0
    platform_machine:x86_64
    platform_python_implementation:PyPy
""").splitlines())


def test_get_marker():
  get_marker()


def test_tokenizer():
  # all valid tokens
  for operator in ('==', '!=', '<=', '>=', '<', '>', 'in', 'not in'):
    assert len(list(tokenize("python_version %s '2.7'" % operator))) == 3, (
        'Did not tokenize: %s' % operator)


def test_evaluate():
  # simple expressions
  assert evaluate(PyPy24, "'ello' in 'hello'") is True
  assert evaluate(PyPy24, "'2.6' < '2.7'") is True
  assert evaluate(PyPy24, "'hello' not in 'ello'") is True
  assert evaluate(PyPy24, "'2.7' >= '2.6'") is True

  # opposites
  assert evaluate(PyPy24, "'ello' not in 'hello'") is False
  assert evaluate(PyPy24, "'2.6' > '2.7'") is False
  assert evaluate(PyPy24, "'hello' in 'ello'") is False
  assert evaluate(PyPy24, "'2.7' <= '2.6'") is False

  # involve subexprs
  assert evaluate(PyPy24, "python_version == '2.7'") is True
  assert evaluate(PyPy24, "python_version != '2.7'") is False
  assert evaluate(PyPy24, "(python_version == '2.7')") is True
  assert evaluate(PyPy24, "python_version in python_full_version") is True

  # unary exprs
  assert evaluate(PyPy24, "''") is False
  assert evaluate(PyPy24, "'hello'") is True
  assert evaluate(PyPy24, "implementation_name") is False
  assert evaluate(PyPy24, "os_name") is True

  # chained exprs
  assert evaluate(PyPy24, "'' and 'hello'") is False
  assert evaluate(PyPy24, "'' or 'hello'") is True
  assert evaluate(PyPy24, "'hello' and ''") is False
  assert evaluate(PyPy24, "'hello' or ''") is True

  # and/or precedence
  assert evaluate(PyPy24, "'' or '' and 'true'") is (False or False and True)
  assert evaluate(PyPy24, "'true' or '' and ''") is (True or False and False)
