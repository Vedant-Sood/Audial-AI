"""Keep browser acceptance failures distinct from best-effort cleanup."""


class BrowserClosed(RuntimeError):
    """A required acceptance operation lost its browser or controller page."""


def browser_is_open(context, page=None):
    browser = context.browser
    return bool(
        browser
        and browser.is_connected()
        and (page is None or not page.is_closed())
    )


def browser_call(context, page, label, operation):
    """Require a live browser, including a disconnect racing the operation.

    Required checks raise on teardown. Returning a default here would let a
    crashed browser skip acceptance assertions and incorrectly pass CI.
    """
    if not browser_is_open(context, page):
        raise BrowserClosed(f"{label}: browser or controller page is closed")
    try:
        return operation()
    except Exception as error:
        if not browser_is_open(context, page) or (
            "Target page, context or browser has been closed" in str(error)
        ):
            raise BrowserClosed(f"{label}: browser closed during the operation") from error
        raise


def browser_cleanup(context, page, label, operation, report):
    """Skip unavailable targets without hiding a failure on a live browser."""
    try:
        browser_call(context, page, label, operation)
    except BrowserClosed as error:
        report.setdefault("cleanup_skipped", []).append(
            {"operation": label, "reason": str(error)}
        )
    except Exception as error:
        report.setdefault("cleanup_errors", []).append(
            {"operation": label, "error": str(error)}
        )
        return False
    return True


def browser_launch_args(extension_path):
    return [
        "--disable-dev-shm-usage",
        "--disable-extensions-except=" + str(extension_path),
        "--load-extension=" + str(extension_path),
        "--autoplay-policy=no-user-gesture-required",
        "--disable-background-networking",
        "--disable-features=OptimizationGuideModelDownloading,OptimizationHints",
    ]
