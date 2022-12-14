"""Machinery for walking a filesystem.

*Walking* a filesystem means recursively visiting a directory and
any sub-directories. It is a fairly common requirement for copying,
searching etc. See :ref:`walking` for details.
"""

from __future__ import unicode_literals

import typing

from collections import defaultdict, deque, namedtuple

from ._repr import make_repr
from .errors import FSError
from .path import abspath, combine, normpath

if typing.TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Collection,
        Iterator,
        List,
        MutableMapping,
        Optional,
        Text,
        Tuple,
        Type,
    )

    from .base import FS
    from .info import Info

    OnError = Callable[[Text, Exception], bool]


_F = typing.TypeVar("_F", bound="FS")


Step = namedtuple("Step", "path, dirs, files")
"""type: a *step* in a directory walk.
"""


# TODO(@althonos): It could be a good idea to create an Abstract Base Class
#                  BaseWalker (with methods walk, files, dirs and info) ?


class Walker(object):
    """A walker object recursively lists directories in a filesystem."""

    def __init__(
        self,
        ignore_errors=False,  # type: bool
        on_error=None,  # type: Optional[OnError]
        search="breadth",  # type: Text
        filter=None,  # type: Optional[List[Text]]
        exclude=None,  # type: Optional[List[Text]]
        filter_dirs=None,  # type: Optional[List[Text]]
        exclude_dirs=None,  # type: Optional[List[Text]]
        max_depth=None,  # type: Optional[int]
        filter_glob=None,  # type: Optional[List[Text]]
        exclude_glob=None,  # type: Optional[List[Text]]
    ):
        # type: (...) -> None
        """Create a new `Walker` instance.

        Arguments:
            ignore_errors (bool): If `True`, any errors reading a
                directory will be ignored, otherwise exceptions will
                be raised.
            on_error (callable, optional): If ``ignore_errors`` is `False`,
                then this callable will be invoked for a path and the
                exception object. It should return `True` to ignore the error,
                or `False` to re-raise it.
            search (str): If ``"breadth"`` then the directory will be
                walked *top down*. Set to ``"depth"`` to walk *bottom up*.
            filter (list, optional): If supplied, this parameter should be
                a list of filename patterns, e.g. ``["*.py"]``. Files will
                only be returned if the final component matches one of the
                patterns.
            exclude (list, optional): If supplied, this parameter should be
                a list of filename patterns, e.g. ``["~*"]``. Files matching
                any of these patterns will be removed from the walk.
            filter_dirs (list, optional): A list of patterns that will be used
                to match directories names. The walk will only open directories
                that match at least one of these patterns. Directories will
                only be returned if the final component matches one of the
                patterns.
            exclude_dirs (list, optional): A list of patterns that will be
                used to filter out directories from the walk. e.g.
                ``['*.svn', '*.git']``. Directory names matching any of these
                patterns will be removed from the walk.
            max_depth (int, optional): Maximum directory depth to walk.
            filter_glob (list, optional): If supplied, this parameter
                should be a list of path patterns e.g. ``["foo/**/*.py"]``.
                Resources will only be returned if their global path or
                an extension of it matches one of the patterns.
            exclude_glob (list, optional): If supplied, this parameter
                should be a list of path patterns e.g. ``["foo/**/*.pyc"]``.
                Resources will not be returned if their global path or
                an extension of it  matches one of the patterns.

        """
        if search not in ("breadth", "depth"):
            raise ValueError("search must be 'breadth' or 'depth'")
        self.ignore_errors = ignore_errors
        if on_error:
            if ignore_errors:
                raise ValueError("on_error is invalid when ignore_errors==True")
        else:
            on_error = self._ignore_errors if ignore_errors else self._raise_errors
        if not callable(on_error):
            raise TypeError("on_error must be callable")

        self.on_error = on_error
        self.search = search
        self.filter = filter
        self.exclude = exclude
        self.filter_dirs = filter_dirs
        self.exclude_dirs = exclude_dirs
        self.filter_glob = filter_glob
        self.exclude_glob = exclude_glob
        self.max_depth = max_depth
        super(Walker, self).__init__()

    @classmethod
    def _ignore_errors(cls, path, error):
        # type: (Text, Exception) -> bool
        """Ignore dir scan errors when called."""
        return True

    @classmethod
    def _raise_errors(cls, path, error):
        # type: (Text, Exception) -> bool
        """Re-raise dir scan errors when called."""
        return False

    @classmethod
    def _calculate_depth(cls, path):
        # type: (Text) -> int
        """Calculate the 'depth' of a directory path (i.e. count components)."""
        _path = path.strip("/")
        return _path.count("/") + 1 if _path else 0

    @classmethod
    def bind(cls, fs):
        # type: (_F) -> BoundWalker[_F]
        """Bind a `Walker` instance to a given filesystem.

        This *binds* in instance of the Walker to a given filesystem, so
        that you won't need to explicitly provide the filesystem as a
        parameter.

        Arguments:
            fs (FS): A filesystem object.

        Returns:
            ~fs.walk.BoundWalker: a bound walker.

        Examples:
            Use this method to explicitly bind a filesystem instance::

                >>> walker = Walker.bind(my_fs)
                >>> for path in walker.files(filter=['*.py']):
                ...     print(path)
                /foo.py
                /bar.py

            Unless you have written a customized walker class, you will
            be unlikely to need to call this explicitly, as filesystem
            objects already have a ``walk`` attribute which is a bound
            walker object::

                >>> for path in my_fs.walk.files(filter=['*.py']):
                ...     print(path)
                /foo.py
                /bar.py

        """
        return BoundWalker(fs)

    def __repr__(self):
        # type: () -> Text
        return make_repr(
            self.__class__.__name__,
            ignore_errors=(self.ignore_errors, False),
            on_error=(self.on_error, None),
            search=(self.search, "breadth"),
            filter=(self.filter, None),
            exclude=(self.exclude, None),
            filter_dirs=(self.filter_dirs, None),
            exclude_dirs=(self.exclude_dirs, None),
            max_depth=(self.max_depth, None),
            filter_glob=(self.filter_glob, None),
            exclude_glob=(self.exclude_glob, None),
        )

    def _iter_walk(
        self,
        fs,  # type: FS
        path,  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
    ):
        # type: (...) -> Iterator[Tuple[Text, Optional[Info]]]
        """Get the walk generator."""
        if self.search == "breadth":
            return self._walk_breadth(fs, path, namespaces=namespaces)
        else:
            return self._walk_depth(fs, path, namespaces=namespaces)

    def _check_open_dir(self, fs, path, info):
        # type: (FS, Text, Info) -> bool
        """Check if a directory should be considered in the walk."""
        full_path = combine(path, info.name)
        if self.exclude_dirs is not None and fs.match(self.exclude_dirs, info.name):
            return False
        if self.exclude_glob is not None and fs.match_glob(
            self.exclude_glob, full_path
        ):
            return False
        if self.filter_dirs is not None and not fs.match(self.filter_dirs, info.name):
            return False
        if self.filter_glob is not None and not fs.match_glob(
            self.filter_glob, full_path, accept_prefix=True
        ):
            return False
        return self.check_open_dir(fs, path, info)

    def check_open_dir(self, fs, path, info):
        # type: (FS, Text, Info) -> bool
        """Check if a directory should be opened.

        Override to exclude directories from the walk.

        Arguments:
            fs (FS): A filesystem instance.
            path (str): Path to directory.
            info (Info): A resource info object for the directory.

        Returns:
            bool: `True` if the directory should be opened.

        """
        return True

    def _check_scan_dir(self, fs, path, info, depth):
        # type: (FS, Text, Info, int) -> bool
        """Check if a directory contents should be scanned."""
        if self.max_depth is not None and depth >= self.max_depth:
            return False
        return self.check_scan_dir(fs, path, info)

    def check_scan_dir(self, fs, path, info):
        # type: (FS, Text, Info) -> bool
        """Check if a directory should be scanned.

        Override to omit scanning of certain directories. If a directory
        is omitted, it will appear in the walk but its files and
        sub-directories will not.

        Arguments:
            fs (FS): A filesystem instance.
            path (str): Path to directory.
            info (Info): A resource info object for the directory.

        Returns:
            bool: `True` if the directory should be scanned.

        """
        return True

    def _check_file(self, fs, dir_path, info):
        # type: (FS, Text, Info) -> bool
        """Check if a filename should be included."""
        # Weird check required for backwards compatibility,
        # when _check_file did not exist.
        if Walker._check_file == type(self)._check_file:
            if self.exclude is not None and fs.match(self.exclude, info.name):
                return False
            if self.exclude_glob is not None and fs.match_glob(
                self.exclude_glob, dir_path + "/" + info.name
            ):
                return False
            if self.filter is not None and not fs.match(self.filter, info.name):
                return False
            if self.filter_glob is not None and not fs.match_glob(
                self.filter_glob, dir_path + "/" + info.name, accept_prefix=True
            ):
                return False
        return self.check_file(fs, info)

    def check_file(self, fs, info):
        # type: (FS, Info) -> bool
        """Check if a filename should be included.

        Override to exclude files from the walk.

        Arguments:
            fs (FS): A filesystem instance.
            info (Info): A resource info object.

        Returns:
            bool: `True` if the file should be included.

        """
        return True

    def _scan(
        self,
        fs,  # type: FS
        dir_path,  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
    ):
        # type: (...) -> Iterator[Info]
        """Get an iterator of `Info` objects for a directory path.

        Arguments:
            fs (FS): A filesystem instance.
            dir_path (str): A path to a directory on the filesystem.
            namespaces (list): A list of additional namespaces to
                include in the `Info` objects.

        Returns:
            ~collections.Iterator: iterator of `Info` objects for
            resources within the given path.

        """
        try:
            for info in fs.scandir(dir_path, namespaces=namespaces):
                yield info
        except FSError as error:
            if not self.on_error(dir_path, error):
                raise

    def walk(
        self,
        fs,  # type: FS
        path="/",  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
    ):
        # type: (...) -> Iterator[Step]
        """Walk the directory structure of a filesystem.

        Arguments:
            fs (FS): A filesystem instance.
            path (str): A path to a directory on the filesystem.
            namespaces (list, optional): A list of additional namespaces
                to add to the `Info` objects.

        Returns:
            collections.Iterator: an iterator of `~fs.walk.Step` instances.

        The return value is an iterator of ``(<path>, <dirs>, <files>)``
        named tuples,  where ``<path>`` is an absolute path to a
        directory, and ``<dirs>`` and ``<files>`` are a list of
        `~fs.info.Info` objects for directories and files in ``<path>``.

        Example:
            >>> walker = Walker(filter=['*.py'])
            >>> for path, dirs, files in walker.walk(my_fs, namespaces=["details"]):
            ...    print("[{}]".format(path))
            ...    print("{} directories".format(len(dirs)))
            ...    total = sum(info.size for info in files)
            ...    print("{} bytes".format(total))
            [/]
            2 directories
            55 bytes
            ...

        """
        _path = abspath(normpath(path))
        dir_info = defaultdict(list)  # type: MutableMapping[Text, List[Info]]
        _walk = self._iter_walk(fs, _path, namespaces=namespaces)
        for dir_path, info in _walk:
            if info is None:
                dirs = []  # type: List[Info]
                files = []  # type: List[Info]
                for _info in dir_info[dir_path]:
                    (dirs if _info.is_dir else files).append(_info)
                yield Step(dir_path, dirs, files)
                del dir_info[dir_path]
            else:
                dir_info[dir_path].append(info)

    def files(self, fs, path="/"):
        # type: (FS, Text) -> Iterator[Text]
        """Walk a filesystem, yielding absolute paths to files.

        Arguments:
            fs (FS): A filesystem instance.
            path (str): A path to a directory on the filesystem.

        Yields:
            str: absolute path to files on the filesystem found
            recursively within the given directory.

        """
        _combine = combine
        for _path, info in self._iter_walk(fs, path=path):
            if info is not None and not info.is_dir:
                yield _combine(_path, info.name)

    def dirs(self, fs, path="/"):
        # type: (FS, Text) -> Iterator[Text]
        """Walk a filesystem, yielding absolute paths to directories.

        Arguments:
            fs (FS): A filesystem instance.
            path (str): A path to a directory on the filesystem.

        Yields:
            str: absolute path to directories on the filesystem found
            recursively within the given directory.

        """
        _combine = combine
        for _path, info in self._iter_walk(fs, path=path):
            if info is not None and info.is_dir:
                yield _combine(_path, info.name)

    def info(
        self,
        fs,  # type: FS
        path="/",  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
    ):
        # type: (...) -> Iterator[Tuple[Text, Info]]
        """Walk a filesystem, yielding tuples of ``(<path>, <info>)``.

        Arguments:
            fs (FS): A filesystem instance.
            path (str): A path to a directory on the filesystem.
            namespaces (list, optional): A list of additional namespaces
                to add to the `Info` objects.

        Yields:
            (str, Info): a tuple of ``(<absolute path>, <resource info>)``.

        """
        _combine = combine
        _walk = self._iter_walk(fs, path=path, namespaces=namespaces)
        for _path, info in _walk:
            if info is not None:
                yield _combine(_path, info.name), info

    def _walk_breadth(
        self,
        fs,  # type: FS
        path,  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
    ):
        # type: (...) -> Iterator[Tuple[Text, Optional[Info]]]
        """Walk files using a *breadth first* search."""
        queue = deque([path])
        push = queue.appendleft
        pop = queue.pop

        _combine = combine
        _scan = self._scan
        _calculate_depth = self._calculate_depth
        _check_open_dir = self._check_open_dir
        _check_scan_dir = self._check_scan_dir
        _check_file = self._check_file

        depth = _calculate_depth(path)

        while queue:
            dir_path = pop()
            for info in _scan(fs, dir_path, namespaces=namespaces):
                if info.is_dir:
                    _depth = _calculate_depth(dir_path) - depth + 1
                    if _check_open_dir(fs, dir_path, info):
                        yield dir_path, info  # Opened a directory
                        if _check_scan_dir(fs, dir_path, info, _depth):
                            push(_combine(dir_path, info.name))
                else:
                    if _check_file(fs, dir_path, info):
                        yield dir_path, info  # Found a file
            yield dir_path, None  # End of directory

    def _walk_depth(
        self,
        fs,  # type: FS
        path,  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
    ):
        # type: (...) -> Iterator[Tuple[Text, Optional[Info]]]
        """Walk files using a *depth first* search."""
        # No recursion!

        _combine = combine
        _scan = self._scan
        _calculate_depth = self._calculate_depth
        _check_open_dir = self._check_open_dir
        _check_scan_dir = self._check_scan_dir
        _check_file = self._check_file
        depth = _calculate_depth(path)

        stack = [
            (path, _scan(fs, path, namespaces=namespaces), None)
        ]  # type: List[Tuple[Text, Iterator[Info], Optional[Tuple[Text, Info]]]]

        push = stack.append

        while stack:
            dir_path, iter_files, parent = stack[-1]
            info = next(iter_files, None)
            if info is None:
                if parent is not None:
                    yield parent
                yield dir_path, None
                del stack[-1]
            elif info.is_dir:
                _depth = _calculate_depth(dir_path) - depth + 1
                if _check_open_dir(fs, dir_path, info):
                    if _check_scan_dir(fs, dir_path, info, _depth):
                        _path = _combine(dir_path, info.name)
                        push(
                            (
                                _path,
                                _scan(fs, _path, namespaces=namespaces),
                                (dir_path, info),
                            )
                        )
                    else:
                        yield dir_path, info
            else:
                if _check_file(fs, dir_path, info):
                    yield dir_path, info


class BoundWalker(typing.Generic[_F]):
    """A class that binds a `Walker` instance to a `FS` instance.

    You will typically not need to create instances of this class
    explicitly. Filesystems have a `~FS.walk` property which returns a
    `BoundWalker` object.

    Example:
        >>> tmp_fs = fs.tempfs.TempFS()
        >>> tmp_fs.walk
        BoundWalker(TempFS())

    A `BoundWalker` is callable. Calling it is an alias for the
    `~fs.walk.BoundWalker.walk` method.

    """

    def __init__(self, fs, walker_class=Walker):
        # type: (_F, Type[Walker]) -> None
        """Create a new walker bound to the given filesystem.

        Arguments:
            fs (FS): A filesystem instance.
            walker_class (type): A `~fs.walk.WalkerBase`
                sub-class. The default uses `~fs.walk.Walker`.

        """
        self.fs = fs
        self.walker_class = walker_class

    def __repr__(self):
        # type: () -> Text
        return "BoundWalker({!r})".format(self.fs)

    def _make_walker(self, *args, **kwargs):
        # type: (*Any, **Any) -> Walker
        """Create a walker instance."""
        walker = self.walker_class(*args, **kwargs)
        return walker

    def walk(
        self,
        path="/",  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
        **kwargs  # type: Any
    ):
        # type: (...) -> Iterator[Step]
        """Walk the directory structure of a filesystem.

        Arguments:
            path (str):
            namespaces (list, optional): A list of namespaces to include
                in the resource information, e.g. ``['basic', 'access']``
                (defaults to ``['basic']``).

        Keyword Arguments:
            ignore_errors (bool): If `True`, any errors reading a
                directory will be ignored, otherwise exceptions will be
                raised.
            on_error (callable): If ``ignore_errors`` is `False`, then
                this callable will be invoked with a path and the exception
                object. It should return `True` to ignore the error, or
                `False` to re-raise it.
            search (str): If ``'breadth'`` then the directory will be
                walked *top down*. Set to ``'depth'`` to walk *bottom up*.
            filter (list): If supplied, this parameter should be a list
                of file name patterns, e.g. ``['*.py']``. Files will only be
                returned if the final component matches one of the
                patterns.
            exclude (list, optional): If supplied, this parameter should be
                a list of filename patterns, e.g. ``['~*', '.*']``. Files matching
                any of these patterns will be removed from the walk.
            filter_dirs (list, optional): A list of patterns that will be used
                to match directories paths. The walk will only open directories
                that match at least one of these patterns.
            exclude_dirs (list): A list of patterns that will be used
                to filter out directories from the walk, e.g. ``['*.svn',
                '*.git']``.
            max_depth (int, optional): Maximum directory depth to walk.

        Returns:
            ~collections.Iterator: an iterator of ``(<path>, <dirs>, <files>)``
            named tuples,  where ``<path>`` is an absolute path to a
            directory, and ``<dirs>`` and ``<files>`` are a list of
            `~fs.info.Info` objects for directories and files in ``<path>``.

        Example:
            >>> walker = Walker(filter=['*.py'])
            >>> for path, dirs, files in walker.walk(my_fs, namespaces=['details']):
            ...     print("[{}]".format(path))
            ...     print("{} directories".format(len(dirs)))
            ...     total = sum(info.size for info in files)
            ...     print("{} bytes".format(total))
            [/]
            2 directories
            55 bytes
            ...

        This method invokes `Walker.walk` with bound `FS` object.

        """
        walker = self._make_walker(**kwargs)
        return walker.walk(self.fs, path=path, namespaces=namespaces)

    __call__ = walk

    def files(self, path="/", **kwargs):
        # type: (Text, **Any) -> Iterator[Text]
        """Walk a filesystem, yielding absolute paths to files.

        Arguments:
            path (str): A path to a directory.

        Keyword Arguments:
            ignore_errors (bool): If `True`, any errors reading a
                directory will be ignored, otherwise exceptions will be
                raised.
            on_error (callable): If ``ignore_errors`` is `False`, then
                this callable will be invoked with a path and the exception
                object. It should return `True` to ignore the error, or
                `False` to re-raise it.
            search (str): If ``'breadth'`` then the directory will be
                walked *top down*. Set to ``'depth'`` to walk *bottom up*.
            filter (list): If supplied, this parameter should be a list
                of file name patterns, e.g. ``['*.py']``. Files will only be
                returned if the final component matches one of the
                patterns.
            exclude (list, optional): If supplied, this parameter should be
                a list of filename patterns, e.g. ``['~*', '.*']``. Files matching
                any of these patterns will be removed from the walk.
            filter_dirs (list, optional): A list of patterns that will be used
                to match directories paths. The walk will only open directories
                that match at least one of these patterns.
            exclude_dirs (list): A list of patterns that will be used
                to filter out directories from the walk, e.g. ``['*.svn',
                '*.git']``.
            max_depth (int, optional): Maximum directory depth to walk.

        Returns:
            ~collections.Iterator: An iterator over file paths (absolute
            from the filesystem root).

        This method invokes `Walker.files` with the bound `FS` object.

        """
        walker = self._make_walker(**kwargs)
        return walker.files(self.fs, path=path)

    def dirs(self, path="/", **kwargs):
        # type: (Text, **Any) -> Iterator[Text]
        """Walk a filesystem, yielding absolute paths to directories.

        Arguments:
            path (str): A path to a directory.

        Keyword Arguments:
            ignore_errors (bool): If `True`, any errors reading a
                directory will be ignored, otherwise exceptions will be
                raised.
            on_error (callable): If ``ignore_errors`` is `False`, then
                this callable will be invoked with a path and the exception
                object. It should return `True` to ignore the error, or
                `False` to re-raise it.
            search (str): If ``'breadth'`` then the directory will be
                walked *top down*. Set to ``'depth'`` to walk *bottom up*.
            filter_dirs (list, optional): A list of patterns that will be used
                to match directories paths. The walk will only open directories
                that match at least one of these patterns.
            exclude_dirs (list): A list of patterns that will be used
                to filter out directories from the walk, e.g. ``['*.svn',
                '*.git']``.
            max_depth (int, optional): Maximum directory depth to walk.

        Returns:
            ~collections.Iterator: an iterator over directory paths
            (absolute from the filesystem root).

        This method invokes `Walker.dirs` with the bound `FS` object.

        """
        walker = self._make_walker(**kwargs)
        return walker.dirs(self.fs, path=path)

    def info(
        self,
        path="/",  # type: Text
        namespaces=None,  # type: Optional[Collection[Text]]
        **kwargs  # type: Any
    ):
        # type: (...) -> Iterator[Tuple[Text, Info]]
        """Walk a filesystem, yielding path and `Info` of resources.

        Arguments:
            path (str): A path to a directory.
            namespaces (list, optional): A list of namespaces to include
                in the resource information, e.g. ``['basic', 'access']``
                (defaults to ``['basic']``).

        Keyword Arguments:
            ignore_errors (bool): If `True`, any errors reading a
                directory will be ignored, otherwise exceptions will be
                raised.
            on_error (callable): If ``ignore_errors`` is `False`, then
                this callable will be invoked with a path and the exception
                object. It should return `True` to ignore the error, or
                `False` to re-raise it.
            search (str): If ``'breadth'`` then the directory will be
                walked *top down*. Set to ``'depth'`` to walk *bottom up*.
            filter (list): If supplied, this parameter should be a list
                of file name patterns, e.g. ``['*.py']``. Files will only be
                returned if the final component matches one of the
                patterns.
            exclude (list, optional): If supplied, this parameter should be
                a list of filename patterns, e.g. ``['~*', '.*']``. Files matching
                any of these patterns will be removed from the walk.
            filter_dirs (list, optional): A list of patterns that will be used
                to match directories paths. The walk will only open directories
                that match at least one of these patterns.
            exclude_dirs (list): A list of patterns that will be used
                to filter out directories from the walk, e.g. ``['*.svn',
                '*.git']``.
            max_depth (int, optional): Maximum directory depth to walk.

        Returns:
            ~collections.Iterable: an iterable yielding tuples of
            ``(<absolute path>, <resource info>)``.

        This method invokes `Walker.info` with the bound `FS` object.

        """
        walker = self._make_walker(**kwargs)
        return walker.info(self.fs, path=path, namespaces=namespaces)


# Allow access to default walker from the module
# For example:
#     fs.walk.walk_files()

default_walker = Walker()
walk = default_walker.walk
walk_files = default_walker.files
walk_info = default_walker.info
walk_dirs = default_walker.dirs
