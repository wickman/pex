# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shutil
from abc import abstractmethod
from uuid import uuid4

from .common import chmod_plus_w, safe_mkdir, safe_mkdtemp, safe_rmtree
from .compatibility import AbstractClass
from .installer import WheelInstaller
from .interpreter import PythonInterpreter
from .package import EggPackage, Package, SourcePackage, WheelPackage
from .platforms import Platform
from .tracer import TRACER
from .util import DistributionHelper


class TranslatorBase(AbstractClass):
  """
    Translate a link into a distribution.
  """
  @abstractmethod
  def translate(self, link):
    pass


class ChainedTranslator(TranslatorBase):
  """
    Glue a sequence of Translators together in priority order.  The first Translator to resolve a
    requirement wins.
  """
  def __init__(self, *translators):
    self._translators = list(filter(None, translators))
    for tx in self._translators:
      if not isinstance(tx, TranslatorBase):
        raise ValueError('Expected a sequence of translators, got %s instead.' % type(tx))

  def translate(self, package, into=None):
    for tx in self._translators:
      dist = tx.translate(package, into=into)
      if dist:
        return dist


class SourceTranslator(TranslatorBase):
  def __init__(self,
               interpreter=PythonInterpreter.get(),
               platform=Platform.current(),
               installer_impl=WheelInstaller):
    self._interpreter = interpreter
    self._installer_impl = installer_impl
    self._platform = platform

  def translate(self, package, into=None):
    """From a SourcePackage, translate to a binary distribution."""
    if not isinstance(package, SourcePackage):
      return None
    
    if not package.local:
      raise ValueError(
          'SourceTranslator can only translate local packages.  You must fetch the package first.')

    installer = None
    version = self._interpreter.version
    unpack_path = Archiver.unpack(package.path)
    into = into or safe_mkdtemp()

    try:
      installer = self._installer_impl(
          unpack_path,
          interpreter=self._interpreter,
          strict=(package.name not in ('distribute', 'setuptools')))
      with TRACER.timed('Packaging %s' % package.name):
        try:
          dist_path = installer.bdist()
        except self._installer_impl.InstallFailure:
          return None
        target_path = os.path.join(into, os.path.basename(dist_path))
        safe_copy(dist_path, target_path)
        target_package = Package.from_href(target_path)
        if not target_package:
          return None
        if not target_package.compatible(self._interpreter.identity, platform=self._platform):
          return None
        return DistributionHelper.distribution_from_path(target_path)
    finally:
      if installer:
        installer.cleanup()
      if unpack_path:
        safe_rmtree(unpack_path)


class BinaryTranslator(TranslatorBase):
  def __init__(self,
               package_type,
               interpreter=PythonInterpreter.get(),
               platform=Platform.current()):
    self._package_type = package_type
    self._platform = platform
    self._identity = interpreter.identity

  def translate(self, package, into=None):
    """From a binary package, translate to a local binary distribution."""
    if not package.local:
      raise ValueError(
          'BinaryTranslator can only translate local packages.  You must fetch the package first.')
    if not isinstance(package, self._package_type):
      return None
    if not package.compatible(identity=self._identity, platform=self._platform):
      return None
    into = into or safe_mkdtemp()
    target_path = os.path.join(into, package.filename)
    safe_copy(package.path, target_path)
    return DistributionHelper.distribution_from_path(bdist)


class EggTranslator(BinaryTranslator):
  def __init__(self, **kw):
    super(EggTranslator, self).__init__(EggPackage, **kw)


class WheelTranslator(BinaryTranslator):
  def __init__(self, **kw):
    super(WheelTranslator, self).__init__(WheelPackage, **kw)


class Translator(object):
  @staticmethod
  def default(platform=Platform.current(), interpreter=None):

    # TODO(wickman) Consider interpreter=None to indicate "universal" packages
    # since the .whl format can support this.
    # Also consider platform=None to require platform-inspecific packages.
    interpreter = interpreter or PythonInterpreter.get()
    shared_options = dict(interpreter=interpreter)
    whl_translator = WheelTranslator(platform=platform, **shared_options)
    egg_translator = EggTranslator(platform=platform, **shared_options)
    source_translator = SourceTranslator(platform=platform, **shared_options)
    return ChainedTranslator(whl_translator, egg_translator, source_translator)
