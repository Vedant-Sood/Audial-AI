"""Compatibility entry point for the integrated local browser companion."""
import argparse
from app.services.browser import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    main(parser.parse_args().port)
