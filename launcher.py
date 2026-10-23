"""Desktop entry point; report startup failures even without a console window."""
if __name__ == "__main__":
    import sys
    if any(argument.startswith("chrome-extension://") for argument in sys.argv[1:]):
        # Chrome and Edge pass the caller origin to the registered console worker.
        # Native messaging must reserve stdout for its length-framed protocol.
        from app.services.native_host import main
        main()
        sys.exit(0)
    # A double-clicked program (no -- arguments) reports failures in a dialog. Decided before
    # Kandha.exe gains its --kandha, which would otherwise make it look like a worker job.
    gui_launch = not any(argument.startswith("--") for argument in sys.argv[1:])
    kandha = False
    try:
        import os
        # Kandha.exe is the same program started with --kandha (packaging/AccessibilityAI.spec)
        if os.path.basename(sys.argv[0]).lower().startswith("kandha") and gui_launch:
            sys.argv.append("--kandha")
            kandha = True
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
        if sys.platform == "win32" and gui_launch:
            import ctypes
            name = "Kandha" if kandha else "Audial-AI"
            ctypes.windll.user32.MessageBoxW(None, name + " could not start.\nDetails: " + str(log),
                                           name, 0x10)
        else:
            traceback.print_exc()
        sys.exit(1)
