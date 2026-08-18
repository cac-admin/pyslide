# -*- coding: utf-8 -*-
""" Optional terminal progress output for upload, polling, and download."""

from __future__ import annotations

import sys
import time


__all__ = [
    "NullBar",
    "PollReporter",
    "ProgressFile",
    "download_bar",
    "extract_progress_pct",
    "format_elapsed",
    "resolve_progress",
    "upload_bar",
]


def resolve_progress(progress):
    """ Decide whether progress output should be shown.

    ``None`` enables it only when stderr is a terminal; ``True`` and ``False``
    force it on or off.
    """
    if progress is not None:
        return bool(progress)
    try:
        return bool(sys.stderr.isatty())
    except Exception:
        return False


def format_elapsed(seconds):
    """ Format a duration as ``Xm YYs``, or ``Hh Xm YYs`` past an hour."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def extract_progress_pct(payload):
    """ Return a 0-100 percentage from a job payload, or ``None``.

    Servers may report ``progress`` as a percentage or as a 0-1 fraction; both
    are accepted, anything else is ignored.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get("progress")
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= number <= 1.0:
        number *= 100.0
    if 0.0 <= number <= 100.0:
        return number
    return None


class NullBar:
    """ Stand-in used when progress output is disabled."""

    def update(self, n=1):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _TextBar:
    """ Minimal stderr percentage reporter used when tqdm is absent."""

    def __init__(self, total=None, desc=""):
        self.total = total if total and total > 0 else None
        self.desc = desc or "progress"
        self.n = 0
        self._last_pct = -1
        self._start = time.monotonic()

    def update(self, n=1):
        self.n += n
        elapsed = format_elapsed(time.monotonic() - self._start)
        if self.total:
            pct = int(100 * self.n / self.total)
            if pct == self._last_pct and self.n < self.total:
                return
            self._last_pct = pct
            line = f"\r{self.desc}: {pct}% [{elapsed}]"
        else:
            line = f"\r{self.desc}: {self.n} bytes [{elapsed}]"
        sys.stderr.write(line)
        sys.stderr.flush()

    def close(self):
        sys.stderr.write("\n")
        sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _byte_bar(total, desc):
    """ Build a byte-oriented tqdm bar, falling back to plain text."""
    try:
        from tqdm import tqdm
    except ImportError:
        return _TextBar(total=total, desc=desc)

    return tqdm(
        total=total if total and total > 0 else None,
        desc=desc,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        file=sys.stderr,
        leave=True,
        mininterval=0.2,
    )


def upload_bar(filename, total, *, enabled=True):
    """ Progress bar for an upload, or :class:`NullBar` when disabled."""
    if not enabled:
        return NullBar()
    return _byte_bar(total, f"Uploading {filename}")


def download_bar(filename, total, *, enabled=True):
    """ Progress bar for a download, or :class:`NullBar` when disabled."""
    if not enabled:
        return NullBar()
    return _byte_bar(total, f"Downloading {filename}")


class ProgressFile:
    """ File wrapper that advances a bar as the HTTP layer reads bytes."""

    def __init__(self, fh, bar=None):
        self._fh = fh
        self._bar = bar or NullBar()

    @property
    def name(self):
        return getattr(self._fh, "name", "upload.bin")

    def read(self, size=-1):
        data = self._fh.read(size)
        if data:
            self._bar.update(len(data))
        return data

    def seek(self, offset, whence=0):
        return self._fh.seek(offset, whence)

    def tell(self):
        return self._fh.tell()

    def close(self):
        return self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class PollReporter:
    """ Single status line describing a job while the client waits."""

    def __init__(self, *, enabled=True):
        self.enabled = bool(enabled)
        self._start = time.monotonic()
        self._last_len = 0
        self._closed = False

    @property
    def elapsed(self):
        return time.monotonic() - self._start

    def _line(self, status, *, next_in=None, payload=None):
        parts = [f"Status: {status or 'unknown'}"]
        pct = extract_progress_pct(payload)
        if pct is not None:
            parts.append(f"{pct:.0f}%")
        message = (payload or {}).get("message") if isinstance(payload, dict) else None
        if message:
            parts.append(str(message))
        parts.append(f"elapsed {format_elapsed(self.elapsed)}")
        if next_in is not None:
            parts.append(f"next check in {int(max(next_in, 0))}s")
        return " | ".join(parts)

    def _write(self, line, *, newline=False):
        pad = max(0, self._last_len - len(line))
        sys.stderr.write("\r" + line + (" " * pad) + ("\n" if newline else ""))
        sys.stderr.flush()
        self._last_len = 0 if newline else len(line)

    def update(self, status, *, next_in=None, payload=None):
        """ Refresh the status line."""
        if not self.enabled or self._closed:
            return
        self._write(self._line(status, next_in=next_in, payload=payload))

    def close(self, final_status=None):
        """ Finish the status line, leaving the last state on screen."""
        if not self.enabled or self._closed:
            return
        self._closed = True
        if final_status is not None:
            self._write(self._line(final_status), newline=True)
        elif self._last_len:
            sys.stderr.write("\n")
            sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
