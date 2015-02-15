import os
import shutil

from pex.crawler import Crawler
from pex.http import Context
from pex.installer import EggInstaller
from pex.iterator import Iterator
from pex.package import EggPackage
from pex.tracer import TRACER

from pkg_resources import Requirement


def _safe_link(src, dst):
  try:
    os.unlink(dst)
  except OSError:
    pass
  os.symlink(src, dst)


def _resolve_and_link(requirement, fetchers, target_link, installer_provider):
  # Short-circuit if there is a local copy
  if os.path.exists(target_link) and os.path.exists(os.path.realpath(target_link)):
    egg = EggPackage(os.path.realpath(target_link))
    if egg.satisfies(requirement):
      return egg

  context = Context.get()
  iterator = Iterator(fetchers=fetchers, crawler=Crawler(context))
  links = [link for link in iterator.iter(requirement) if isinstance(link, SourcePackage)]

  with TIMER.timed('Interpreter cache resolving %s' % requirement, V=2):
    for link in links:
      with TIMER.timed('Fetching %s' % link, V=3):
        sdist = context.fetch(link)

      with TIMER.timed('Installing %s' % link, V=3):
        installer = installer_provider(sdist)
        dist_location = installer.bdist()
        target_location = os.path.join(os.path.dirname(target_link), os.path.basename(dist_location))
        shutil.move(dist_location, target_location)
        _safe_link(target_location, target_link)

      return EggPackage(target_location)


def resolve_interpreter(cache, interpreter, requirement, fetchers):
  """Resolve an interpreter with a specific requirement.

     Given a :class:`PythonInterpreter` and a requirement, return an
     interpreter with the capability of resolving that requirement or
     ``None`` if it's not possible to install a suitable requirement."""

  requirement = requirement if isinstance(requirement, Requirement) else Requirement.parse(
      requirement)
  interpreter_dir = os.path.join(cache, str(interpreter.identity))

  # short circuit
  if interpreter.satisfies([requirement]):
    return interpreter

  def installer_provider(sdist):
    return EggInstaller(
        Archiver.unpack(sdist),
        strict=requirement.key != 'setuptools',
        interpreter=interpreter)

  egg = _resolve_and_link(
      requirement,
      fetchers,
      os.path.join(interpreter_dir, requirement.key),
      installer_provider,
      logger=logger)

  if egg:
    return interpreter.with_extra(egg.name, egg.raw_version, egg.path)
