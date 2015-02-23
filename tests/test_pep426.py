import textwrap

from pex.pep426 import PEP426Marker, evaluate, get_marker, tokenize


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
    assert len(list(tokenize(PyPy24, "python_version %s '2.7'" % operator))) == 3, (
        'Did not tokenize: %s' % operator)


EXPRESSIONS = (
  # regular
  "'ello' in 'hello'",
  "'2.6' < '2.7'",
  "'hello' not in 'ello'",
  "'2.7' >= '2.6'",

  # opposites
  "'ello' not in 'hello'",
  "'2.6' > '2.7'",
  "'hello' in 'ello'",
  "'2.7' <= '2.6'",

  # involve subexprs
  "python_version == '2.7'",
  "python_version != '2.7'",
  "(python_version == '2.7')",
  "python_version in python_full_version",

  # unary exprs
  "''",
  "'hello'",
  "implementation_name",
  "os_name",

  # chained exprs
  "'' and 'hello'",
  "'' or 'hello'",
  "'hello' and ''",
  "'hello' or ''",

  # and/or precedence
  "'' or '' and 'true'",
  "'true' or '' and ''",
)


def test_evaluate():
  def real_eval(marker, expr):
    return eval(' '.join(map(str, tokenize(marker, expr))))

  for expr in EXPRESSIONS:
    assert evaluate(PyPy24, expr) == bool(real_eval(PyPy24, expr)), 'Failed: %r' % expr
