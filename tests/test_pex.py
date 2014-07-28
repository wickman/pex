# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import textwrap

import pytest
from twitter.common.contextutil import temporary_dir

from pex.compatibility import nested
from pex.pex_builder import PEXBuilder


def write_pex(td, exe_contents):
  with open(os.path.join(td, 'exe.py'), 'w') as fp:
    fp.write(exe_contents)

  pb = PEXBuilder(path=td)
  pb.set_executable(os.path.join(td, 'exe.py'))
  pb.freeze()

  return pb


def run_pex(pex, env=None):
  po = subprocess.Popen(pex, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
  po.wait()
  return po.stdout.read(), po.returncode


def run_test(body, env=None):
  with nested(temporary_dir(), temporary_dir()) as (td1, td2):
    pb = write_pex(td1, body)
    pex = os.path.join(td2, 'app.pex')
    pb.build(pex)
    return run_pex(pex, env=env)


@pytest.mark.skipif('sys.version_info > (3,)')
def test_pex_uncaught_exceptions():
  body = "raise Exception('This is an exception')"
  so, rc = run_test(body)
  assert b'This is an exception' in so, 'Standard out was: %s' % so
  assert rc == 1


def test_pex_sys_exit_does_not_raise():
  body = "import sys; sys.exit(2)"
  so, rc = run_test(body)
  assert so == b'', 'Should not print SystemExit exception.'
  assert rc == 2


def test_pex_atexit_swallowing():
  body = textwrap.dedent("""
  import atexit

  def raise_on_exit():
    raise Exception('This is an exception')

  atexit.register(raise_on_exit)
  """)

  so, rc = run_test(body)
  assert so == b''
  assert rc == 0

  env_copy = os.environ.copy()
  env_copy.update(PEX_TEARDOWN_VERBOSE='1')
  so, rc = run_test(body, env=env_copy)
  assert b'This is an exception' in so
  assert rc == 0
