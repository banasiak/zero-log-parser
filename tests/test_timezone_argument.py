"""
Tests for numeric --timezone values ('-8', '+1', '5.5'), which both command
lines pass to the utils helpers as strings. They used to go straight to
ZoneInfo, which rejects them, so the hour offsets the --timezone help text
advertises always failed; zone names are unchanged.

Same conventions as the other files in this directory: plain test_*
functions, stdlib only, no dataset files checked in.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.zero_log_parser.utils import (apply_timezone_to_datetime, get_timezone_offset,
                                       offset_hours_from_string)


def test_numeric_strings_are_hour_offsets():
    assert get_timezone_offset('-6') == -6 * 3600
    assert get_timezone_offset('+1') == 3600
    assert get_timezone_offset('5.5') == int(5.5 * 3600)
    assert get_timezone_offset(' -8 ') == -8 * 3600


def test_integers_still_work():
    assert get_timezone_offset(-8) == -8 * 3600


def test_names_are_not_mistaken_for_offsets():
    for name in ('UTC', 'America/Denver', 'Etc/GMT+7', 'nan', 'inf', '-'):
        assert offset_hours_from_string(name) is None, name


def test_time_filters_accept_numeric_strings():
    dt = apply_timezone_to_datetime(datetime(2026, 10, 15, 12, 0), '-6')
    assert dt.utcoffset() == timedelta(hours=-6)


def test_command_line_accepts_a_negative_offset():
    # A minimal REV0 file is enough to get past argument handling and into
    # get_timezone_offset, which is where '-6' used to fail.
    from test_undecoded_and_corrupted_rendering import _write_minimal_rev0_file
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'test.bin')
        _write_minimal_rev0_file(path, b'')
        out = os.path.join(d, 'test.txt')
        result = subprocess.run([sys.executable, os.path.join(ROOT, 'zero_log_parser.py'),
                                 '--timezone', '-6', '-o', out, path],
                                capture_output=True, text=True, cwd=ROOT)
        assert result.returncode == 0, result.stderr[-2000:]
        assert 'UTC-6' in open(out, encoding='utf-8-sig').read()


def test_command_line_works_without_the_package_on_the_path():
    # python -I leaves the script's own directory off sys.path, so neither
    # src.zero_log_parser.utils nor zero_log_parser.utils can be imported;
    # get_timezone_offset used to be left undefined and fail with NameError.
    from test_undecoded_and_corrupted_rendering import _write_minimal_rev0_file
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'test.bin')
        _write_minimal_rev0_file(path, b'')
        for tz in ('-6', 'UTC', None):
            out = os.path.join(d, 'test.txt')
            args = [sys.executable, '-I', os.path.join(ROOT, 'zero_log_parser.py'), '-o', out, path]
            if tz is not None:
                args[3:3] = ['--timezone', tz]
            result = subprocess.run(args, capture_output=True, text=True, cwd=d)
            assert result.returncode == 0, (tz, result.stderr[-2000:])
