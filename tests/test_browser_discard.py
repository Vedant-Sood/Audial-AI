import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts.browser_discard import detached_discard_restore
from scripts.browser_lifecycle import BrowserClosed


DISCARDED = {
    "phase": "discarded", "previous_id": 42,
    "tab": {"id": 43, "discarded": True, "active": False},
    "observed": {"id": 43, "discarded": True},
}
RESTORED = {"phase": "restored", "tab": {"id": 43, "discarded": False, "active": True}}
COMPLETE = {"phase": "complete", "removed": True}


def observer_session(observations, exit_code=None):
    detached = threading.Event()
    state = {"tabs": []}
    browser = SimpleNamespace(is_connected=lambda: not detached.is_set(), close=detached.set)
    context = SimpleNamespace(browser=browser, audial_browser_process=SimpleNamespace(poll=lambda: exit_code, returncode=exit_code))

    def evaluate(expression, arguments=None):
        assert not detached.is_set(), "No Playwright interaction is allowed after detaching"
        if arguments is None:
            return "test-extension"

        def deliver():
            assert detached.wait(5)
            for observation in observations:
                if "tab" in observation:
                    state["tabs"] = [observation["tab"]]
                request = Request(
                    arguments["endpoint"], data=json.dumps(observation).encode(),
                    headers={"Origin": "chrome-extension://test-extension"},
                )
                try:
                    with urlopen(request, timeout=5) as response:
                        assert json.load(response)["ok"]
                except HTTPError:
                    break

        threading.Thread(target=deliver, daemon=True).start()

    page = SimpleNamespace(is_closed=lambda: detached.is_set(), evaluate=evaluate)
    return context, page, lambda: state["tabs"]


def test_detached_discard_requires_actual_states_and_matching_bridge_observations():
    context, page, snapshot = observer_session([DISCARDED, RESTORED, COMPLETE])
    report = {}
    detached_discard_restore(context, page, 42, report, snapshot)
    assert report["discard_identity"] == {"before": 42, "after": 43}
    assert report["bridge_discard_observations"]["discarded"]["discarded"]
    assert not report["bridge_discard_observations"]["restored"]["discarded"]


@pytest.mark.parametrize("observations", [
    [{**DISCARDED, "tab": {"id": 43, "discarded": False, "active": False}}],
    [DISCARDED, {**RESTORED, "tab": {"id": 99, "discarded": False, "active": True}}],
    [COMPLETE],
])
def test_invalid_or_incomplete_browser_observations_never_pass(observations):
    context, page, _ = observer_session(observations)
    with pytest.raises(AssertionError):
        detached_discard_restore(context, page, 42, {})


def test_browser_exit_before_observations_remains_a_failure():
    context, page, _ = observer_session([], exit_code=3221225477)
    with pytest.raises(BrowserClosed, match="3221225477"):
        detached_discard_restore(context, page, 42, {})
