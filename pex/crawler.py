# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import threading

from .compatibility import PY3
from .link import Link
from .http import Context

if PY3:
  from queue import Empty, Queue
  from urllib.parse import urlparse
else:
  from Queue import Empty, Queue
  from urlparse import urlparse


class PageParser(object):
  HREF_RE = re.compile(r"""href=(?:"([^"]*)"|\'([^\']*)\'|([^>\s\n]*))""", re.I | re.S)
  REL_RE = re.compile(r"""<[^>]*\srel\s*=\s*['"]?([^'">]+)[^>]*>""", re.I)
  REL_SKIP_EXTENSIONS = frozenset(['.zip', '.tar', '.tar.gz', '.tar.bz2', '.tgz', '.exe'])
  REL_TYPES = frozenset(['homepage', 'download'])

  @classmethod
  def href_match_to_url(cls, match):
    def pick(group):
      return '' if group is None else group
    return pick(match.group(1)) or pick(match.group(2)) or pick(match.group(3))

  @classmethod
  def rel_links(cls, page):
    """return rel= links that should be scraped, skipping obviously data links."""
    for match in cls.REL_RE.finditer(page):
      href, rel = match.group(0), match.group(1)
      if rel not in cls.REL_TYPES:
        continue
      href_match = cls.HREF_RE.search(href)
      if href_match:
        href = cls.href_match_to_url(href_match)
        parsed_href = urlparse(href)
        if any(parsed_href.path.endswith(ext) for ext in cls.REL_SKIP_EXTENSIONS):
          continue
        yield href

  @classmethod
  def links(cls, page):
    """return all links on a page, including potentially rel= links."""
    for match in cls.HREF_RE.finditer(page):
      yield cls.href_match_to_url(match)


def partition(L, pred):
  return filter(lambda v: not pred(v), L), filter(lambda v: pred(v), L)


def crawl_local(link):
  try:
    dirents = os.listdir(link.path)
  except OSError as e:
    # tracer XXX
    return set(), set()
  files, dirs = partition([os.path.join(link.path, fn) for fn in dirents], os.path.isdir)
  return set(map(Link.from_filename, files)), set(map(Link.from_filename, dirs))


def crawl_remote(context, link):
  try:
    content = context.read(link)
  except context.Error as e:
    # tracer XXX
    return set(), set()
  links = set(link.join(href) for href in PageParser.links(content))
  rel_links = set(link.join(href) for href in PageParser.rel_links(content))
  return links, rel_links


def crawl(context, link):
  if link.local:
    return crawl_local(link)
  elif link.remote:
    return crawl_remote(context, link)
  else:
    # Unknown scheme
    return set(), set()


class Crawler(object):
  def __init__(self, context=None, threads=1):
    self._threads = threads
    self.context = context or Context.get()

  def crawl(self, link_or_links, follow_links=False):
    links, seen = set(), set()
    queue = Queue()
    converged = threading.Event()

    def execute():
      while not converged.is_set():
        try:
          link = queue.get(timeout=0.1)
        except Empty:
          continue
        if link not in seen:
          seen.add(link)
          roots, rels = crawl(self.context, link)
          links.update(roots)
          if follow_links:
            for rel in rels:
              if rel not in seen:
                queue.put(rel)
        queue.task_done()

    for link in Link.wrap_iterable(link_or_links):
      queue.put(link)

    workers = []
    for _ in range(self._threads):
      worker = threading.Thread(target=execute)
      workers.append(worker)
      worker.daemon = True
      worker.start()

    queue.join()
    converged.set()

    for worker in workers:
      worker.join()

    return links
