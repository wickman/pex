# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from abc import abstractmethod

from .base import maybe_requirement
from .compatibility import AbstractClass, PY3

if PY3:
  import urllib.parse as urlparse
  from urllib.parse import urljoin
else:
  import urlparse
  from urlparse import urljoin


class LocatorBase(AbstractClass):
  """A locator takes a Requirement and tells us where to crawl to find it."""

  @abstractmethod
  def urls(self, req):
    raise NotImplementedError


class Locator(LocatorBase):
  def __init__(self, urls):
    self._urls = urls

  def urls(self, _):
    return self._urls


class PyPILocator(LocatorBase):
  PYPI_BASE = 'https://pypi.python.org/simple/'

  def __init__(self, pypi_base=PYPI_BASE):
    pypi_url = urlparse.urlparse(pypi_base)
    if not pypi_url.scheme:
      self.__pypi_base = 'http://' + pypi_base
    else:
      self.__pypi_base = pypi_base

  def urls(self, req):
    req = maybe_requirement(req)
    return [urljoin(self.__pypi_base, '%s/' % req.project_name)]
