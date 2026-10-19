"""Dedicated native-messaging executable entry point for PyInstaller."""
from app.services.native_host import main

if __name__ == "__main__":
    main()
