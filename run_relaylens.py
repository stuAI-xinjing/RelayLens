"""Run directly with Python; pip installation is optional."""
import sys

if sys.platform == 'win32':
    for stream in (sys.stdout,sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8',errors='replace')
        except AttributeError:
            pass

from relaylens.audit import main

if __name__ == '__main__':
    raise SystemExit(main())
