"""Desktop entry point; report startup failures even without a console window."""
if __name__ == "__main__":
    try:
        from app.main import main
        main()
    except Exception:
        import os
        from pathlib import Path
        import sys
        import traceback
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AccessibilityAI"
        base.mkdir(parents=True, exist_ok=True)
        log = base / "startup-error.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32" and "--smoke-test" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "AccessibilityAI could not start.\nDetails: " + str(log),
                                           "AccessibilityAI", 0x10)
        else:
            traceback.print_exc()
        sys.exit(1)
