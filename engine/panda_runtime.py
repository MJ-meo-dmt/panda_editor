"""Deprecated compatibility module for POC 0.1.1.

The renderer moved to :mod:`engine.panda_process` because creating Panda3D's
Win32/WGL graphics window inside a standard Python worker thread can deadlock.
Use :class:`engine.viewport.ViewportHost` instead.
"""

from .panda_process import PandaProcessRuntime

__all__ = ['PandaProcessRuntime']
