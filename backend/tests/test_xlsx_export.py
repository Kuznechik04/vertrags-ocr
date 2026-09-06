from app.services.xlsx_export import _excel_safe


def test_excel_safe_neutralizes_formula_prefixes():
    assert _excel_safe("=1+1") == "'=1+1"
    assert _excel_safe("+SUM(A1)") == "'+SUM(A1)"
    assert _excel_safe("-1+1") == "'-1+1"
    assert _excel_safe("@SUM(1)") == "'@SUM(1)"


def test_excel_safe_leaves_normal_values_untouched():
    assert _excel_safe("Max Mustermann") == "Max Mustermann"
    assert _excel_safe("") == ""
    assert _excel_safe("12,50 €") == "12,50 €"
