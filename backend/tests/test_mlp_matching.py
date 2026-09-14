from app.ocr.base import FieldSpec
from app.ocr.mlp_template import MLP_FIELDS
from app.ocr.mock_model import MockOCRModel, PageData, Word


def _page(text: str) -> PageData:
    words = []
    for index, value in enumerate(text.split()):
        words.append(
            Word(
                text=value,
                x0=index / 100,
                x1=(index + 1) / 100,
                top=0.1,
                bottom=0.12,
            )
        )
    return PageData(lines=[words])


def _field(key: str) -> FieldSpec:
    _, label, patterns = next(field for field in MLP_FIELDS if field[0] == key)
    return FieldSpec(field_key=key, field_label=label, patterns=patterns)


def test_mlp_date_and_money_patterns_accept_form_variants():
    model = MockOCRModel()
    page = _page(
        "Versicherungsbeginn: 01.03.2026 "
        "Gesamtbeitrag inkl. Versicherungssteuer: 1.234,56 EUR"
    )

    start = model._match_field_in_pages(_field("versicherungsbeginn").patterns or [], [page])
    total = model._match_field_in_pages(
        _field("gesamtbeitrag_versicherungssteuer").patterns or [], [page]
    )

    assert start.value == "01.03.2026"
    assert total.value == "1.234,56 EUR"


def test_mlp_checkbox_pattern_matches_checked_form_value():
    model = MockOCRModel()
    page = _page("Feuerrohbau: x")

    match = model._match_field_in_pages(_field("feuerrohbau").patterns or [], [page])

    assert match.match_status == "matched"
    assert match.value.lower() == "x"


def test_mlp_template_contains_all_requested_fields_in_order():
    keys = [field[0] for field in MLP_FIELDS]

    assert keys[:4] == ["name", "strasse_hausnummer", "plz_wohnort", "geburtsdatum"]
    assert keys[-1] == "kontoinhaber_iban"
    assert len(keys) == 49


def test_account_holder_fields_do_not_use_the_first_same_named_field():
    model = MockOCRModel()
    page = PageData(
        lines=[
            [
                Word(text="Name", x0=0.1, x1=0.2, top=0.1, bottom=0.12),
                Word(text="Max", x0=0.21, x1=0.3, top=0.1, bottom=0.12),
            ],
            [
                Word(text="Gibt", x0=0.1, x1=0.2, top=0.2, bottom=0.22),
                Word(text="es", x0=0.21, x1=0.25, top=0.2, bottom=0.22),
                Word(text="einen", x0=0.26, x1=0.35, top=0.2, bottom=0.22),
                Word(text="abweichenden", x0=0.36, x1=0.52, top=0.2, bottom=0.22),
                Word(text="Kontoinhaber?", x0=0.53, x1=0.7, top=0.2, bottom=0.22),
            ],
            [
                Word(text="Name", x0=0.1, x1=0.2, top=0.3, bottom=0.32),
                Word(text="Erika", x0=0.21, x1=0.3, top=0.3, bottom=0.32),
            ],
        ]
    )

    match = model._match_field_in_pages(_field("kontoinhaber_name").patterns or [], [page])

    assert match.match_status == "matched"
    assert match.value == "Erika"
