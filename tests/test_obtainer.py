# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pkg_resources import get_build_platform, Requirement

from pex.fetcher import Fetcher
from pex.interpreter import PythonInterpreter
from pex.obtainer import Obtainer
from pex.package import EggPackage, SourcePackage, WheelPackage, Package


def test_package_precedence():
  source = SourcePackage('psutil-0.6.1.tar.gz')
  egg = EggPackage('psutil-0.6.1-py2.6.egg')
  whl = WheelPackage('psutil-0.6.1-cp26-none-macosx_10_4_x86_64.whl')

  # default precedence
  assert Obtainer.package_precedence(whl) > Obtainer.package_precedence(egg)
  assert Obtainer.package_precedence(egg) > Obtainer.package_precedence(source)
  assert Obtainer.package_precedence(whl) > Obtainer.package_precedence(source)

  # overridden precedence
  PRECEDENCE = (EggPackage, WheelPackage)
  assert Obtainer.package_precedence(source, PRECEDENCE) == (source.version, -1)  # unknown rank
  assert Obtainer.package_precedence(whl, PRECEDENCE) > Obtainer.package_precedence(
      source, PRECEDENCE)
  assert Obtainer.package_precedence(egg, PRECEDENCE) > Obtainer.package_precedence(
      whl, PRECEDENCE)


class FakeCrawler(object):
  def __init__(self, hrefs):
    self._hrefs = hrefs
    self.opener = None

  def crawl(self, *args, **kw):
    return self._hrefs


class FakeObtainer(Obtainer):
  def __init__(self, links):
    self.__links = list(links)
    super(FakeObtainer, self).__init__()

  def _iter_unordered(self, req):
    return iter(self.__links)


def test_iter_ordering():
  pi = PythonInterpreter.get()
  tgz = SourcePackage('psutil-0.6.1.tar.gz')
  egg = EggPackage('psutil-0.6.1-py%s-%s.egg' % (pi.python, get_build_platform()))
  whl = WheelPackage('psutil-0.6.1-cp%s-none-%s.whl' % (
      pi.python.replace('.', ''),
      get_build_platform().replace('-', '_').replace('.', '_').lower()))
  req = Requirement.parse('psutil')

  assert list(FakeObtainer([tgz, egg, whl]).iter(req)) == [whl, egg, tgz]
  assert list(FakeObtainer([egg, tgz, whl]).iter(req)) == [whl, egg, tgz]
