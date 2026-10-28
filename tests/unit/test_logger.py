"""Unit tests for logger robustness against third-party log records."""
import logging

from src.logger import EnsureSourceFilter, Log_Format


def _format(record, with_filter):
    formatter = logging.Formatter(Log_Format, datefmt='%Y-%m-%d %H:%M:%S', style='{')
    if with_filter:
        EnsureSourceFilter().filter(record)
    return formatter.format(record)


def _foreign_record(msg='Created 10,000 records', level=logging.INFO):
    """A record as a third-party library (pyogrio, GDAL, ...) would emit it —
    without the 'source' extra that PALM-GeM's own wrappers attach."""
    return logging.LogRecord('pyogrio._io', level, __file__, 1, msg, (), None)


def test_foreign_record_crashes_without_filter():
    """Documents the failure mode the filter exists for."""
    try:
        _format(_foreign_record(), with_filter=False)
        crashed = False
    except (KeyError, ValueError):
        crashed = True
    assert crashed


def test_filter_makes_foreign_record_formattable():
    line = _format(_foreign_record(), with_filter=True)
    assert 'Created 10,000 records' in line
    assert 'INFO' in line  # source filled from the level name


def test_filter_keeps_own_source_untouched():
    record = _foreign_record('palm-gem message')
    record.source = 'PROGRESS'
    line = _format(record, with_filter=True)
    assert 'PROGRESS' in line
    assert 'palm-gem message' in line
