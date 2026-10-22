"""Desktop entry point; report startup failures even without a console window."""
if __name__ == "__main__":
    import sys
    if any(argument.startswith("chrome-extension://") for argument in sys.argv[1:]):
        # Chrome and Edge pass the caller origin to the registered console worker.
        # Native messaging must reserve stdout for its length-framed protocol.
        from app.services.native_host import main
        main()
        sys.exit(0)
    try:
        import os
        # Kandha.exe is the same program started with --kandha (packaging/AccessibilityAI.spec)
        if os.path.basename(sys.argv[0]).lower().startswith("kandha") and not any(a.startswith("--") for a in sys.argv[1:]):
            sys.argv.append("--kandha")
        from app.main import main
        main()
    except Exception:
        import sys
        import traceback
        from app.utils.paths import data_root
        log = data_root() / "startup-error.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        # Worker failures belong in their captured diagnostics and desktop
        # notification, rather than a dialog blocking an unattended operation.
        gui_launch = not any(argument.startswith("--") for argument in sys.argv[1:])
        if sys.platform == "win32" and gui_launch:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "Audial-AI could not start.\nDetails: " + str(log),
                                           "Audial-AI", 0x10)
        else:
            traceback.print_exc()
        sys.exit(1)
