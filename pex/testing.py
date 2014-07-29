# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import os
import random
import tempfile
import subprocess
import zipfile
from textwrap import dedent

from .common import safe_mkdir, safe_rmtree
from .compatibility import nested
from .installer import EggInstaller, Packager
from .pex_builder import PEXBuilder
from .util import DistributionHelper


@contextlib.contextmanager
def temporary_dir():
  td = tempfile.mkdtemp()
  try:
    yield td
  finally:
    safe_rmtree(td)


def random_bytes(length):
  return ''.join(
      map(chr, (random.randint(ord('a'), ord('z')) for _ in range(length)))).encode('utf-8')


@contextlib.contextmanager
def temporary_content(content_map, interp=None, seed=31337):
  """Write content to disk where content is map from string => (int, string).

     If target is int, write int random bytes.  Otherwise write contents of string."""
  random.seed(seed)
  interp = interp or {}
  with temporary_dir() as td:
    for filename, size_or_content in content_map.items():
      safe_mkdir(os.path.dirname(os.path.join(td, filename)))
      with open(os.path.join(td, filename), 'wb') as fp:
        if isinstance(size_or_content, int):
          fp.write(random_bytes(size_or_content))
        else:
          fp.write((size_or_content % interp).encode('utf-8'))
    yield td


def yield_files(directory):
  for root, _, files in os.walk(directory):
    for f in files:
      filename = os.path.join(root, f)
      rel_filename = os.path.relpath(filename, directory)
      yield filename, rel_filename


def write_zipfile(directory, dest, reverse=False):
  with contextlib.closing(zipfile.ZipFile(dest, 'w')) as zf:
    for filename, rel_filename in sorted(yield_files(directory), reverse=reverse):
      zf.write(filename, arcname=rel_filename)
  return dest


PROJECT_CONTENT = {
  'setup.py': dedent('''
      from setuptools import setup

      setup(
          name=%(project_name)r,
          version='0.0.0',
          zip_safe=%(zip_safe)r,
          packages=['my_package'],
          package_data={'my_package': ['package_data/*.dat']},
      )
  '''),
  'MANIFEST.in': dedent('''
  include setup.py
  '''),
  'my_package/__init__.py': 0,
  'my_package/my_module.py': 'def do_something():\n  print("hello world!")\n',
  'my_package/package_data/resource1.dat': 1000,
  'my_package/package_data/resource2.dat': 1000,
}


@contextlib.contextmanager
def make_installer(name='my_project', installer_impl=EggInstaller, zip_safe=True):
  interp = {'project_name': name, 'zip_safe': zip_safe}
  with temporary_content(PROJECT_CONTENT, interp=interp) as td:
    yield installer_impl(td)


def make_sdist(name='my_project', zip_safe=True):
  with make_installer(name=name, installer_impl=Packager, zip_safe=zip_safe) as packager:
    return packager.sdist()


@contextlib.contextmanager
def make_bdist(name='my_project', installer_impl=EggInstaller, zipped=False, zip_safe=True):
  with make_installer(name=name, installer_impl=installer_impl, zip_safe=zip_safe) as installer:
    dist_location = installer.bdist()
    if zipped:
      yield DistributionHelper.distribution_from_path(dist_location)
    else:
      with temporary_dir() as td:
        extract_path = os.path.join(td, os.path.basename(dist_location))
        with contextlib.closing(zipfile.ZipFile(dist_location)) as zf:
          zf.extractall(extract_path)
        yield DistributionHelper.distribution_from_path(extract_path)


def write_simple_pex(td, exe_contents, dists=None):
  dists = dists or []

  with open(os.path.join(td, 'exe.py'), 'w') as fp:
    fp.write(exe_contents)

  pb = PEXBuilder(path=td)
  for dist in dists:
    pb.add_egg(dist.location)
  pb.set_executable(os.path.join(td, 'exe.py'))
  pb.freeze()

  return pb


# TODO(wickman) Why not PEX.run?
def run_simple_pex(pex, env=None):
  po = subprocess.Popen(pex, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
  po.wait()
  return po.stdout.read(), po.returncode


def run_simple_pex_test(body, env=None):
  with nested(temporary_dir(), temporary_dir()) as (td1, td2):
    pb = write_simple_pex(td1, body)
    pex = os.path.join(td2, 'app.pex')
    pb.build(pex)
    return run_simple_pex(pex, env=env)
