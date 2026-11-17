"""Tests for JWT access-token creation and verification."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from security import (
    DEFAULT_ACCESS_TOKEN_EXPIRES,
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

# Test-only credentials. Production code must load its signing key from the
# TASKFLOW_JWT_SECRET environment variable.
TEST_SECRET = (
    "test-only-taskflow-secret-never-use-in-production-"
    "with-enough-length-for-hs512-tests"
)
OTHER_TEST_SECRET = (
    "test-only-different-secret-never-use-in-production-"
    "with-enough-length-for-hs512-tests"
)
TEST_SUBJECT = "user-123"


def make_claims(**overrides):
    """Build valid claims so individual tests can remove or corrupt one."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": TEST_SUBJECT,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


def test_create_access_token_returns_a_signed_hs256_token():
    token = create_access_token(TEST_SUBJECT, TEST_SECRET)

    assert isinstance(token, str)
    assert token.count(".") == 2
    assert jwt.get_unverified_header(token)["alg"] == JWT_ALGORITHM


def test_decode_access_token_accepts_a_valid_token():
    token = create_access_token(TEST_SUBJECT, TEST_SECRET)

    payload = decode_access_token(token, TEST_SECRET)

    assert isinstance(payload, dict)
    assert set(payload) == {"sub", "iat", "exp"}


def test_decoded_token_has_the_correct_subject():
    token = create_access_token(TEST_SUBJECT, TEST_SECRET)

    payload = decode_access_token(token, TEST_SECRET)

    assert payload["sub"] == TEST_SUBJECT


def test_token_contains_issued_at_and_default_expiration_claims():
    before = int(datetime.now(timezone.utc).timestamp())
    token = create_access_token(TEST_SUBJECT, TEST_SECRET)
    after = int(datetime.now(timezone.utc).timestamp())

    payload = decode_access_token(token, TEST_SECRET)

    assert before <= payload["iat"] <= after
    assert payload["exp"] - payload["iat"] == int(
        DEFAULT_ACCESS_TOKEN_EXPIRES.total_seconds()
    )
    assert payload["exp"] - payload["iat"] == 30 * 60


def test_custom_expiration_is_applied():
    expires_delta = timedelta(minutes=5)

    token = create_access_token(
        TEST_SUBJECT,
        TEST_SECRET,
        expires_delta=expires_delta,
    )
    payload = decode_access_token(token, TEST_SECRET)

    assert payload["exp"] - payload["iat"] == int(expires_delta.total_seconds())


def test_expired_token_is_rejected():
    token = create_access_token(
        TEST_SUBJECT,
        TEST_SECRET,
        expires_delta=timedelta(minutes=-5),
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, TEST_SECRET)


def test_tampered_token_is_rejected():
    token = create_access_token(TEST_SUBJECT, TEST_SECRET)
    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(tampered, TEST_SECRET)


def test_token_signed_with_a_different_secret_is_rejected():
    token = create_access_token(TEST_SUBJECT, TEST_SECRET)

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token, OTHER_TEST_SECRET)


def test_token_missing_subject_is_rejected():
    claims = make_claims()
    del claims["sub"]
    token = jwt.encode(claims, TEST_SECRET, algorithm=JWT_ALGORITHM)

    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token, TEST_SECRET)


@pytest.mark.parametrize("invalid_subject", ["", "   ", 123, None])
def test_token_with_invalid_subject_is_rejected(invalid_subject):
    token = jwt.encode(
        make_claims(sub=invalid_subject),
        TEST_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, TEST_SECRET)


@pytest.mark.parametrize("invalid_subject", ["", "   ", 123, None])
def test_create_access_token_rejects_invalid_subject(invalid_subject):
    with pytest.raises(ValueError, match="subject"):
        create_access_token(invalid_subject, TEST_SECRET)


def test_unapproved_signing_algorithm_is_rejected():
    token = jwt.encode(make_claims(), TEST_SECRET, algorithm="HS512")

    with pytest.raises(jwt.InvalidAlgorithmError):
        decode_access_token(token, TEST_SECRET)


def test_hash_generation_and_format():
    password = "CorrectHorseBatteryStaple123!"
    hashed = hash_password(password)

    assert isinstance(hashed, str)
    assert hashed.startswith("$argon2id$")


def test_hash_differs_from_plaintext():
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert password not in hashed


def test_same_password_produces_different_hashes():
    password = "RepeatablePassword123!"
    hash1 = hash_password(password)
    hash2 = hash_password(password)

    assert hash1 != hash2
    assert hash1.startswith("$argon2id$")
    assert hash2.startswith("$argon2id$")


def test_correct_password_verification():
    password = "MySecurePassword123!"
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True


def test_incorrect_password_verification():
    password = "MySecurePassword123!"
    hashed = hash_password(password)

    assert verify_password("WrongPassword123!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(password, "") is False
    assert verify_password(password, "invalid$argon2$hash") is False


@pytest.mark.parametrize("invalid_password", ["", None, 12345, [], {}])
def test_invalid_password_input_raises_value_error(invalid_password):
    with pytest.raises(ValueError, match="password must be a non-empty string"):
        hash_password(invalid_password)

