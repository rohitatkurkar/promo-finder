"""The Supabase client: settings, headers, retries, errors, and the key never leaking. No network is used."""

import pytest
import requests

from promo_finder.cloud import CloudError, SupabaseClient, SupabaseConfig, supabase_config
from conftest import SUPABASE_TEST_KEY, SUPABASE_TEST_URL, FakeResponse, FakeSupabase


def client(transport, key=SUPABASE_TEST_KEY):
    sleeps = []
    return SupabaseClient(SupabaseConfig(SUPABASE_TEST_URL, key), transport=transport, sleep=sleeps.append), sleeps


def test_settings_are_optional_and_checked():
    assert supabase_config({}) is None
    assert supabase_config({"SUPABASE_URL": SUPABASE_TEST_URL}) is None
    config = supabase_config({"SUPABASE_URL": SUPABASE_TEST_URL + "/", "SUPABASE_SECRET_KEY": SUPABASE_TEST_KEY})
    assert config.url == SUPABASE_TEST_URL and SUPABASE_TEST_KEY not in repr(config)
    with pytest.raises(ValueError, match="https"):
        supabase_config({"SUPABASE_URL": "http://project.supabase.test", "SUPABASE_SECRET_KEY": "k"})


def test_a_new_secret_key_goes_only_in_the_apikey_header_and_a_legacy_key_also_as_bearer():
    fake = FakeSupabase()
    client(fake)[0].select("reviews", {"run_id": "r"})
    assert fake.calls[0]["headers"]["apikey"] == SUPABASE_TEST_KEY and "Authorization" not in fake.calls[0]["headers"]
    client(fake, key="eyJhbGciOiJIUzI1NiJ9.legacy.jwt")[0].select("reviews", {"run_id": "r"})
    assert fake.calls[1]["headers"]["Authorization"] == "Bearer eyJhbGciOiJIUzI1NiJ9.legacy.jwt"


def test_select_sends_equality_filters_and_order():
    fake = FakeSupabase()
    client(fake)[0].select("reviews", {"run_id": "run_1", "reviewer_hash": "ab"}, order="saved_at.asc")
    params = fake.calls[0]["params"]
    assert params["run_id"] == "eq.run_1" and params["reviewer_hash"] == "eq.ab" and params["order"] == "saved_at.asc"


def test_insert_can_skip_rows_already_stored():
    fake = FakeSupabase()
    row = {"review_id": "0" * 32, "saved_at": "2026-11-10T00:00:00Z"}
    model, _ = client(fake)
    model.insert("reviews", [row], ignore_duplicates_on="review_id")
    model.insert("reviews", [row], ignore_duplicates_on="review_id")
    assert len(fake.rows) == 1
    assert "resolution=ignore-duplicates" in fake.calls[0]["headers"]["Prefer"]


def test_a_server_error_is_retried_then_succeeds():
    replies = [FakeResponse(503, text="busy"), FakeResponse(200, payload=[])]
    model, sleeps = client(lambda *args, **kwargs: replies.pop(0))
    assert model.select("reviews", {"run_id": "r"}) == []
    assert sleeps == [0.5]


def test_a_refused_key_is_not_retried_and_never_shown():
    calls = []

    def refuse(*args, **kwargs):
        calls.append(1)
        return FakeResponse(401, text=f"bad key {SUPABASE_TEST_KEY}")

    with pytest.raises(CloudError) as caught:
        client(refuse)[0].select("reviews", {"run_id": "r"})
    assert caught.value.kind == "auth" and len(calls) == 1
    assert SUPABASE_TEST_KEY not in str(caught.value) and SUPABASE_TEST_KEY not in caught.value.detail


def test_an_outage_fails_quickly_after_two_retries_without_the_key():
    def down(*args, **kwargs):
        raise requests.ConnectionError(f"cannot reach host, key={SUPABASE_TEST_KEY}")

    model, sleeps = client(down)
    with pytest.raises(CloudError) as caught:
        model.insert("reviews", [{}])
    assert caught.value.kind == "network" and sleeps == [0.5, 1.0]
    assert SUPABASE_TEST_KEY not in caught.value.detail


def test_a_rejected_row_is_not_retried():
    replies = [FakeResponse(400, text="violates check constraint")]
    with pytest.raises(CloudError) as caught:
        client(lambda *args, **kwargs: replies.pop(0))[0].insert("reviews", [{}])
    assert caught.value.kind == "rejected"
