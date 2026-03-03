"""Tests for SHML SDK exception hierarchy and raise_for_status helper."""

import pytest

from shml.exceptions import (
    SHMLError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    RateLimitError,
    JobError,
    JobSubmissionError,
    JobTimeoutError,
    JobCancelledError,
    ConfigError,
    ProfileNotFoundError,
    ValidationError,
    IntegrationError,
    MLflowError,
    NessieError,
    FiftyOneError,
    FeatureStoreError,
    raise_for_status,
)


# ── Hierarchy Tests ──────────────────────────────────────────────────────


class TestExceptionHierarchy:
    """Verify all exceptions inherit from SHMLError."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "exc_class",
        [
            AuthenticationError,
            PermissionDeniedError,
            NotFoundError,
            RateLimitError,
            JobError,
            ConfigError,
            IntegrationError,
        ],
    )
    def test_direct_subclasses(self, exc_class):
        assert issubclass(exc_class, SHMLError)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "exc_class,parent",
        [
            (JobSubmissionError, JobError),
            (JobTimeoutError, JobError),
            (JobCancelledError, JobError),
            (ProfileNotFoundError, ConfigError),
            (ValidationError, ConfigError),
            (MLflowError, IntegrationError),
            (NessieError, IntegrationError),
            (FiftyOneError, IntegrationError),
            (FeatureStoreError, IntegrationError),
        ],
    )
    def test_nested_subclasses(self, exc_class, parent):
        assert issubclass(exc_class, parent)
        assert issubclass(exc_class, SHMLError)

    @pytest.mark.unit
    def test_shml_error_is_exception(self):
        assert issubclass(SHMLError, Exception)


# ── Construction Tests ───────────────────────────────────────────────────


class TestExceptionConstruction:
    """Verify exceptions can be instantiated with expected arguments."""

    @pytest.mark.unit
    def test_shml_error_message(self):
        err = SHMLError("something went wrong")
        assert str(err) == "something went wrong"

    @pytest.mark.unit
    def test_authentication_error(self):
        err = AuthenticationError("invalid token")
        assert "invalid token" in str(err)
        assert isinstance(err, SHMLError)

    @pytest.mark.unit
    def test_job_error_preserves_context(self):
        err = JobSubmissionError("GPU unavailable")
        with pytest.raises(JobError):
            raise err


# ── raise_for_status Tests ───────────────────────────────────────────────


class TestRaiseForStatus:
    """Verify raise_for_status maps HTTP codes to the correct exception."""

    @pytest.mark.unit
    def test_401_raises_authentication_error(self):
        with pytest.raises(AuthenticationError):
            raise_for_status(401, "Unauthorized")

    @pytest.mark.unit
    def test_403_raises_permission_denied(self):
        with pytest.raises(PermissionDeniedError):
            raise_for_status(403, "Forbidden")

    @pytest.mark.unit
    def test_404_raises_not_found(self):
        with pytest.raises(NotFoundError):
            raise_for_status(404, "Not Found")

    @pytest.mark.unit
    def test_429_raises_rate_limit(self):
        with pytest.raises(RateLimitError):
            raise_for_status(429, "Too Many Requests")

    @pytest.mark.unit
    def test_200_does_not_raise(self):
        # Success codes should not raise
        raise_for_status(200, "OK")

    @pytest.mark.unit
    def test_500_raises_shml_error(self):
        with pytest.raises(SHMLError):
            raise_for_status(500, "Internal Server Error")
