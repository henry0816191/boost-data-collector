"""
File/path operations shared across apps (e.g. sanitize_filename).
"""

import os
import re
import urllib.parse


_WINDOWS_RESERVED_NAMES = frozenset({"CON", "PRN", "AUX", "NUL"})


def _is_windows_reserved_name(name):
    """True if name (no extension) is a Windows reserved device name."""
    if not name:
        return False
    upper = name.upper()
    if upper in _WINDOWS_RESERVED_NAMES:
        return True
    if re.match(r"^COM[1-9]$", upper):
        return True
    if re.match(r"^LPT[1-9]$", upper):
        return True
    return False


def sanitize_filename(filename):
    """Sanitize filename to remove invalid characters for Windows/Linux/Mac."""
    filename = urllib.parse.unquote(filename)
    invalid_chars = r'[\\/:*?"<>|]'
    filename = re.sub(invalid_chars, "_", filename)
    filename = re.sub(r":[a-zA-Z0-9_+-]+:", "", filename)
    filename = re.sub(r"&[a-zA-Z]+;", "_", filename)
    filename = re.sub(r"[^\w\s\-_\.\(\)\[\]]", "_", filename)
    filename = re.sub(r"[_\s]+", "_", filename)
    filename = filename.strip("_ ")
    if filename in (".", ".."):
        filename = "downloaded_file"
    elif filename:
        name, ext = os.path.splitext(filename)
        if _is_windows_reserved_name(name):
            filename = name + "_" + ext
    if not filename:
        filename = "downloaded_file"
    max_length = 200
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[: max_length - len(ext)] + ext
    return filename


__all__ = ["sanitize_filename"]
