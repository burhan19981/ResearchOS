"""DatasetValidator contract tests (Phase 8A)."""

from __future__ import annotations

from researchos.specification.validators import (
    ClassificationDatasetValidator,
    GenericStructuralValidator,
    available_formats,
    get_validator,
)


def test_available_formats_lists_registered_validators():
    formats = available_formats()
    assert "generic" in formats
    assert "classification" in formats
    assert formats == sorted(formats)  # deterministic ordering


def test_get_validator_returns_generic_for_unknown_format():
    validator = get_validator("some-format-nobody-registered")
    assert isinstance(validator, GenericStructuralValidator)


def test_get_validator_returns_generic_for_none():
    validator = get_validator(None)
    assert isinstance(validator, GenericStructuralValidator)


def test_get_validator_is_case_insensitive():
    validator = get_validator("CLASSIFICATION")
    assert isinstance(validator, ClassificationDatasetValidator)


def test_generic_validator_valid_dataset():
    outcome = GenericStructuralValidator().validate({
        "sample_count": 1000, "split_definition": {"train": 0.8, "test": 0.2}, "source_uri": "s3://x/",
    })
    assert outcome.is_valid
    assert outcome.errors == []


def test_generic_validator_negative_sample_count_is_invalid():
    outcome = GenericStructuralValidator().validate({"sample_count": -5})
    assert not outcome.is_valid
    assert any("sample_count" in e for e in outcome.errors)


def test_generic_validator_missing_fields_produce_warnings_not_errors():
    outcome = GenericStructuralValidator().validate({})
    assert outcome.is_valid  # missing optional fields are warnings, not errors
    assert outcome.warnings  # but they are surfaced


def test_generic_validator_split_definition_not_summing_correctly_warns():
    outcome = GenericStructuralValidator().validate({
        "sample_count": 1000, "split_definition": {"train": 0.5, "test": 0.1}, "source_uri": "s3://x/",
    })
    assert outcome.is_valid  # a warning, not an error
    assert any("split_definition" in w for w in outcome.warnings)


def test_generic_validator_split_definition_wrong_type_is_invalid():
    outcome = GenericStructuralValidator().validate({"split_definition": "not-an-object"})
    assert not outcome.is_valid


def test_classification_validator_requires_class_definition():
    outcome = ClassificationDatasetValidator().validate({"sample_count": 100})
    assert not outcome.is_valid
    assert any("class_definition" in e for e in outcome.errors)


def test_classification_validator_rejects_duplicate_labels():
    outcome = ClassificationDatasetValidator().validate({"class_definition": ["a", "b", "a"]})
    assert not outcome.is_valid
    assert any("duplicate" in e for e in outcome.errors)


def test_classification_validator_valid_dataset():
    outcome = ClassificationDatasetValidator().validate({
        "sample_count": 100, "class_definition": ["pass", "fail"],
        "split_definition": {"train": 0.8, "test": 0.2}, "source_uri": "s3://x/",
    })
    assert outcome.is_valid


def test_validator_is_deterministic_across_calls():
    metadata = {"sample_count": 50, "class_definition": ["a", "b"]}
    first = ClassificationDatasetValidator().validate(metadata)
    second = ClassificationDatasetValidator().validate(metadata)
    assert first.to_json() == second.to_json()


def test_validator_never_touches_the_filesystem_or_network(monkeypatch):
    """A validator operates purely on the supplied metadata dict — it
    must never attempt to open source_uri as a real location."""
    import builtins

    def _forbidden_open(*args, **kwargs):
        raise AssertionError("DatasetValidator must never open a file")

    monkeypatch.setattr(builtins, "open", _forbidden_open)
    outcome = GenericStructuralValidator().validate({"source_uri": "s3://totally-real-bucket/data/", "sample_count": 10})
    assert outcome.is_valid
