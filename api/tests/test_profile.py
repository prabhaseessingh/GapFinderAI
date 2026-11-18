from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.schemas.profile import PRIVACY_POLICY_VERSION
from tests.helpers import auth_headers, make_student, token_for

pytestmark = pytest.mark.integration


def test_signup_acceptance_is_recorded_from_metadata(client: Any, db: Session) -> None:
    student = make_student(db)
    token = token_for(student, metadata={"privacy_policy_version": PRIVACY_POLICY_VERSION})
    profile = client.get("/profile", headers={"authorization": f"Bearer {token}"}).json()
    assert profile["privacy_policy_version"] == PRIVACY_POLICY_VERSION
    assert profile["privacy_accepted_at"] is not None


def test_explicit_acceptance_and_locale(client: Any, db: Session) -> None:
    student = make_student(db)
    headers = auth_headers(student)
    assert client.get("/profile", headers=headers).json()["privacy_accepted_at"] is None
    stale = client.patch("/profile", json={"accept_privacy_policy_version": "old"}, headers=headers)
    assert stale.status_code == 409
    updated = client.patch(
        "/profile",
        headers=headers,
        json={"accept_privacy_policy_version": PRIVACY_POLICY_VERSION, "selected_locale": "te-IN"},
    ).json()
    assert updated["selected_locale"] == "te-IN" and updated["privacy_accepted_at"]
    assert (
        client.patch("/profile", json={"selected_locale": "fr"}, headers=headers).status_code == 422
    )
