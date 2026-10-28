"""Unit-Tests für `apply_field_dependencies` (MLP: Kontoinhaber-Felder werden
"not_required", wenn es keinen abweichenden Kontoinhaber gibt)."""
import pytest

from app.ocr.base import FieldPrediction
from app.ocr.mlp_template import MLP_FIELD_DEPENDENCIES, apply_field_dependencies, normalize_status_values


def _pred(key: str, value: str | None, status: str = "matched") -> FieldPrediction:
    return FieldPrediction(
        field_key=key,
        field_label=key,
        value=value,
        confidence=0.9 if value else 0.0,
        bbox=(0.1, 0.1, 0.1, 0.1) if value else None,
        match_status=status,
    )


def _predictions(parent_value: str | None) -> list[FieldPrediction]:
    return [
        _pred("abweichender_kontoinhaber", parent_value, "matched" if parent_value else "field_not_found"),
        _pred("kontoinhaber_name", None, "data_not_found"),
        # Fehltreffer des ungescopten "Firmenname"-Musters
        _pred("kontoinhaber_firmenname", "Muster GmbH"),
        _pred("name", "Max Mustermann"),
    ]


@pytest.mark.parametrize("parent_value", ["nein", " Nein ", "NO"])
def test_children_not_required_when_parent_is_no(parent_value):
    predictions = _predictions(parent_value)
    apply_field_dependencies(predictions, MLP_FIELD_DEPENDENCIES)
    by_key = {p.field_key: p for p in predictions}

    for key in ("kontoinhaber_name", "kontoinhaber_firmenname"):
        assert by_key[key].match_status == "not_required"
        assert by_key[key].value is None
        assert by_key[key].bbox is None
        assert by_key[key].confidence == 0.0
    assert by_key["name"].value == "Max Mustermann"
    assert by_key["name"].match_status == "matched"


@pytest.mark.parametrize("parent_value", ["ja", "x", None])
def test_children_unchanged_otherwise(parent_value):
    predictions = _predictions(parent_value)
    apply_field_dependencies(predictions, MLP_FIELD_DEPENDENCIES)
    by_key = {p.field_key: p for p in predictions}

    assert by_key["kontoinhaber_name"].match_status == "data_not_found"
    assert by_key["kontoinhaber_firmenname"].value == "Muster GmbH"
    assert by_key["kontoinhaber_firmenname"].match_status == "matched"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("nicht gewinscht", "nicht gewünscht"),
        ("Nicht  Gewunscht", "nicht gewünscht"),
        ("gewinscht", "gewünscht"),
        ("gewünscht", "gewünscht"),
        ("50.000 EUR", "50.000 EUR"),
        ("Nein", "Nein"),
        ("Bauleistung gewünscht und mehr", "Bauleistung gewünscht und mehr"),
    ],
)
def test_normalize_status_values(raw, expected):
    predictions = [_pred("ausstattung_kunstwert_t512807u", raw)]
    normalize_status_values(predictions)
    assert predictions[0].value == expected
