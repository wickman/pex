from pex.testing import run_simple_pex_test


def test_pex_coverage():
  body = ""
  _, rc = run_simple_pex_test(body, coverage=True)
  assert rc == 0
