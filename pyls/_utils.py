# Copyright 2017 Palantir Technologies, Inc.
import functools
import logging
import os
import re
import threading

log = logging.getLogger(__name__)

FIRST_CAP_RE = re.compile('(.)([A-Z][a-z]+)')
ALL_CAP_RE = re.compile('([a-z0-9])([A-Z])')


def debounce(interval_s):
    """Debounce calls to this function until interval_s seconds have passed."""
    def wrapper(func):
        @functools.wraps(func)
        def debounced(*args, **kwargs):
            if hasattr(debounced, '_timer'):
                debounced._timer.cancel()
            debounced._timer = threading.Timer(interval_s, func, args, kwargs)
            debounced._timer.start()
        return debounced
    return wrapper


def camel_to_underscore(string):
    s1 = FIRST_CAP_RE.sub(r'\1_\2', string)
    return ALL_CAP_RE.sub(r'\1_\2', s1).lower()


def find_parents(root, path, names):
    """Find files matching the given names relative to the given path.

    Args:
        path (str): The file path to start searching up from.
        names (List[str]): The file/directory names to look for.
        root (str): The directory at which to stop recursing upwards.

    Note:
        The path MUST be within the root.
    """
    if not root:
        return []

    if not os.path.commonprefix((root, path)):
        log.warning("Path %s not in %s", path, root)
        return []

    # Split the relative by directory, generate all the parent directories, then check each of them.
    # This avoids running a loop that has different base-cases for unix/windows
    # e.g. /a/b and /a/b/c/d/e.py -> ['/a/b', 'c', 'd']
    dirs = [root] + os.path.relpath(os.path.dirname(path), root).split(os.path.sep)

    # Search each of /a/b/c, /a/b, /a
    while dirs:
        search_dir = os.path.join(*dirs)
        existing = list(filter(os.path.exists, [os.path.join(search_dir, n) for n in names]))
        if existing:
            return existing
        dirs.pop()

    # Otherwise nothing
    return []


def list_to_string(value):
    return ",".join(value) if type(value) == list else value


def merge_dicts(dict_a, dict_b):
    """Recursively merge dictionary b into dictionary a.

    If override_nones is True, then
    """
    def _merge_dicts_(a, b):
        for key in set(a.keys()).union(b.keys()):
            if key in a and key in b:
                if isinstance(a[key], dict) and isinstance(b[key], dict):
                    yield (key, dict(_merge_dicts_(a[key], b[key])))
                elif b[key] is not None:
                    yield (key, b[key])
                else:
                    yield (key, a[key])
            elif key in a:
                yield (key, a[key])
            elif b[key] is not None:
                yield (key, b[key])
    return dict(_merge_dicts_(dict_a, dict_b))


def race_hooks(hook_caller, pool, **kwargs):
    """Given a pluggy hook spec, execute impls in parallel returning the first non-None result.

    Note this does not support a lot of pluggy functionality, e.g. hook wrappers.
    """
    impls = hook_caller._nonwrappers + hook_caller._wrappers
    log.debug("Racing hook impls for hook %s: %s", hook_caller, impls)

    if not impls:
        return None

    def _apply(impl):
        try:
            return impl, impl.function(**kwargs)
        except Exception:
            log.exception("Failed to run hook %s", impl.plugin_name)
            raise

    # imap unordered gives us an iterator over the items in the order they finish.
    # We have to be careful to set chunksize to 1 to ensure hooks each get their own thread.
    # Unfortunately, there's no way to interrupt these threads, so we just have to leave them be.
    for impl, result in pool.imap_unordered(_apply, impls, chunksize=1):
        if result is not None:
            log.debug("Hook from plugin %s returned: %s", impl.plugin_name, result)
            return result


def format_docstring(contents):
    """Python doc strings come in a number of formats, but LSP wants markdown.

    Until we can find a fast enough way of discovering and parsing each format,
    we can do a little better by at least preserving indentation.
    """
    contents = contents.replace('\t', '\u00A0' * 4)
    contents = contents.replace('  ', '\u00A0' * 2)
    contents = contents.replace('*', '\\*')
    return contents
