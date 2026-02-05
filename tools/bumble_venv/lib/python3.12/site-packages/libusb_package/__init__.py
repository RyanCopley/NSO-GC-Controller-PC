# Copyright (c) 2021 Chris Reed
#
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import atexit
import ctypes.util
import functools
import platform
import sys
from typing import (Any, Optional, TYPE_CHECKING)

# importlib.resources isn't available before Python 3.7, so if importing it
# fails we import the backport.
try:
    from importlib import resources
except ImportError:
    import importlib_resources as resources # type:ignore

from ._version import version as __version__

if TYPE_CHECKING:
    from usb.backend import IBackend
    from pathlib import Path

__all__ = ['find_library', 'get_libusb1_backend', 'find']

# Look up the expected shared library filename extension by the OS.
_LIBRARY_MAP_EXT = {
        'Darwin': '.dylib',
        'Linux': '.so',
        'Windows': '.dll',
    }
_LIBRARY_EXT = _LIBRARY_MAP_EXT.get(platform.system(), ".so")
_LIBRARY_NAME = 'libusb-1.0' + _LIBRARY_EXT

@functools.lru_cache()
def get_library_path() -> Optional["Path"]:
    """@brief Returns the path to included library, if there is one."""
    if resources.is_resource(__name__, _LIBRARY_NAME):
        path_resource = resources.path(__name__, _LIBRARY_NAME)
        path = path_resource.__enter__()

        @atexit.register
        def cleanup():
            path_resource.__exit__(None, None, None)

        return path
    else:
        return None


def find_library(candidate: str) -> Optional[str]:
    """@brief Look for a package resource starting with the provided candidate name.

    This function effectively implements the `find_library` callback used by pyusb's backends.
    However, it is general enough to be used for any code that needs a libusb library.

    @retval str Path to the contained library matching the candidate name.
    @retval None No library matching the candidate name is contained in libusb_package.
    """
    lib_path = get_library_path()
    if not lib_path:
        # There is no library included in our installation, fall back to ctypes' find_library.
        return ctypes.util.find_library(candidate)

    lib_name = lib_path.name

    if lib_name.startswith(candidate) \
            or ((platform.system() == "Linux") and lib_name.startswith("lib" + candidate)):
        return str(lib_path)

    # We don't have a matching library.
    return None


# pyusb is imported within the following functions so it isn't strictly required as a
# dependency unless these functions are used.

@functools.lru_cache()
def get_libusb1_backend() -> Optional["IBackend"]:
    """@brief Return a usb backend for pyusb."""
    import usb.backend.libusb1
    return usb.backend.libusb1.get_backend(find_library=find_library)


# TODO refine the type signature of find()
def find(*args: Any, **kwargs: Any) -> Any:
    """@brief Wrap pyusb's usb.core,find() function.

    A 'backend' keyword argument will override the default of using `get_libusb1_backend()`.
    If None is passed for 'backend', then the default backend lookup method of pyusb will
    be used.
    """
    import usb.core
    backend = kwargs.pop('backend', get_libusb1_backend())
    return usb.core.find(*args, backend=backend, **kwargs)


