from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.browser_lifecycle import BrowserClosed, browser_call, browser_cleanup


def session():
    browser = SimpleNamespace(is_connected=Mock(return_value=True))
    context = SimpleNamespace(browser=browser)
    page = SimpleNamespace(is_closed=Mock(return_value=False))
    return context, page


@pytest.mark.parametrize("closed_target", ["browser", "page", "missing_browser"])
def test_required_operation_fails_without_touching_closed_targets(closed_target):
    context, page = session()
    if closed_target == "browser":
        context.browser.is_connected.return_value = False
    elif closed_target == "page":
        page.is_closed.return_value = True
    else:
        context.browser = None
    operation = Mock()

    with pytest.raises(BrowserClosed, match="discarded tab lookup"):
        browser_call(context, page, "discarded tab lookup", operation)

    operation.assert_not_called()


def test_disconnect_racing_a_required_operation_still_fails_acceptance():
    context, page = session()
    original = RuntimeError("Target page, context or browser has been closed")

    def disconnect():
        context.browser.is_connected.return_value = False
        raise original

    with pytest.raises(BrowserClosed, match="restore") as captured:
        browser_call(context, page, "restore", disconnect)
    assert captured.value.__cause__ is original

    remove_tab = Mock()
    report = {}
    assert browser_cleanup(context, page, "remove suspended tab", remove_tab, report)
    remove_tab.assert_not_called()
    assert report["cleanup_skipped"][0]["operation"] == "remove suspended tab"


def test_target_closed_before_disconnect_event_is_reported_as_teardown():
    context, page = session()
    operation = Mock(side_effect=RuntimeError("Target page, context or browser has been closed"))
    with pytest.raises(BrowserClosed):
        browser_call(context, page, "wait after discard", operation)


def test_live_browser_errors_are_preserved():
    context, page = session()
    original = AssertionError("Discard did not retain the actual tab identity")
    with pytest.raises(AssertionError) as captured:
        browser_call(context, page, "discard check", Mock(side_effect=original))
    assert captured.value is original

    report = {}
    assert not browser_cleanup(context, page, "remove tab", Mock(side_effect=original), report)
    assert report["cleanup_errors"][0]["error"] == str(original)


def test_live_browser_operation_returns_the_observed_tab():
    context, page = session()
    observed = {"id": 42, "discarded": True}
    assert browser_call(context, page, "lookup", lambda: observed) is observed
