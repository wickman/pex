from __future__ import absolute_import

from collections import Iterable
import os
import posixpath

from .compatibility import PY3, string as compatible_string

if PY3:
  import urllib.parse as urlparse
else:
  import urlparse


class Link(object):
  """An HTTP link."""

  @classmethod
  def wrap(cls, url):
    if isinstance(url, cls):
      return url
    elif isinstance(url, compatible_string):
      return cls(url)
    else:
      raise ValueError('url must be either a string or Link.')

  @classmethod
  def wrap_iterable(cls, url_or_urls):
    try:
      return [cls.wrap(url_or_urls)]
    except ValueError:
      pass

    if isinstance(url_or_urls, Iterable):
      return [cls.wrap(url) for url in url_or_urls]

    raise ValueError('url_or_urls must be string/Link or iterable of strings/Links')

  @classmethod
  def normalize(cls, filename):
    return 'file://' + os.path.realpath(os.path.expanduser(filename))

  @classmethod
  def from_filename(cls, filename):
    return cls(cls.normalize(filename))

  def __init__(self, url):
    purl = urlparse.urlparse(url)
    if purl.scheme == '':
      purl = urlparse.urlparse(self.normalize(url))
    self._url = purl

  def __eq__(self, link):
    return self.__class__ == link.__class__ and self._url == link._url
  
  def __hash__(self):
    return hash(self._url)

  @property
  def filename(self):
    return posixpath.basename(self._url.path)

  @property
  def path(self):
    return self._url.path

  @property
  def url(self):
    return urlparse.urlunparse(self._url)

  @property
  def local(self):
    """Is the url a local file?"""
    return self._url.scheme in ('', 'file')

  @property
  def remote(self):
    """Is the url a remote file?"""
    return self._url.scheme in ('http', 'https')

  def __repr__(self):
    return '%s(%r)' % (self.__class__.__name__, self.url)
