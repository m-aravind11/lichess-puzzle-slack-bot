from unittest.mock import MagicMock

import pytest
import requests

import daily_puzzle
from daily_puzzle import Constants, LichessDailyPuzzle


def ok(payload: dict) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    return response


def failing(status: int) -> MagicMock:
    response = MagicMock(status_code=status, text="error")
    response.raise_for_status.side_effect = requests.HTTPError(f"{status}", response=response)
    return response


@pytest.fixture
def get(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(daily_puzzle.requests, "get", mock)
    monkeypatch.setattr(daily_puzzle.time, "sleep", MagicMock())
    return mock


def test_request_has_a_timeout(get):
    get.return_value = ok({"id": "p1"})

    assert LichessDailyPuzzle()._fetch_json_with_retries("url") == {"id": "p1"}
    assert get.call_args.kwargs["timeout"] == Constants.FETCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(), failing(503)])
def test_transient_failure_is_retried_with_backoff(get, failure):
    get.side_effect = [failure, ok({"id": "p1"})]

    assert LichessDailyPuzzle()._fetch_json_with_retries("url") == {"id": "p1"}
    daily_puzzle.time.sleep.assert_called_once_with(Constants.FETCH_RETRY_DELAYS_SECONDS[0])


@pytest.mark.parametrize("status", [429, 404])
def test_client_error_fails_without_retrying(get, status):
    get.return_value = failing(status)

    with pytest.raises(requests.HTTPError):
        LichessDailyPuzzle()._fetch_json_with_retries("url")
    assert get.call_count == 1
    daily_puzzle.time.sleep.assert_not_called()


def test_gives_up_after_every_delay_is_used(get):
    get.side_effect = requests.Timeout()

    with pytest.raises(requests.Timeout):
        LichessDailyPuzzle()._fetch_json_with_retries("url")
    assert get.call_count == len(Constants.FETCH_RETRY_DELAYS_SECONDS) + 1
    assert [c.args[0] for c in daily_puzzle.time.sleep.call_args_list] == list(Constants.FETCH_RETRY_DELAYS_SECONDS)
