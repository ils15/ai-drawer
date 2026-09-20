"""Parameter tool tests against the behavioral fake: list, add, modify, plus
units conversion through the fake's expression engine."""

import _fusion_test_bootstrap  # noqa: F401  (installs adsk mock + parent pkg shim)
from fake_fusion import values


def test_add_parameter_creates_a_user_parameter(fusion, call, mcp):
    payload = mcp.ok(call("add_parameter", name="width", expression="25 mm"))
    assert payload["name"] == "width"
    assert payload["expression"] == "25 mm"
    # Parameter.value is internal centimetres: 25 mm -> 2.5 cm.
    assert payload["value"] == 2.5


def test_add_parameter_requires_name_and_expression(fusion, call, mcp):
    assert "missing required argument" in mcp.error(call("add_parameter", name="w"))


def test_add_parameter_requires_an_active_design(fusion_empty, call, mcp):
    message = mcp.error(call("add_parameter", name="w", expression="1 mm"))
    assert "no active Fusion design" in message


def test_add_parameter_rejects_duplicates(fusion, call, mcp):
    fusion.add_parameter("width", "10 mm")
    message = mcp.error(call("add_parameter", name="width", expression="20 mm"))
    assert "already exists" in message


def test_add_parameter_reports_a_bad_expression(fusion, monkeypatch, call, mcp):
    def boom(self, name, value_input, unit="", comment=""):
        raise RuntimeError("bad expression")

    monkeypatch.setattr(fusion.user_parameters, "add", boom)
    message = mcp.error(call("add_parameter", name="bad", expression="*"))
    assert "refused to create parameter" in message


def test_add_parameter_unit_labels_the_parameter(fusion, call, mcp):
    payload = mcp.ok(call("add_parameter", name="angle", expression="45 deg", unit="deg"))
    assert payload["value"] == 45.0
    parameter = fusion.user_parameters.itemByName("angle")
    assert parameter.unit == "deg"


def test_list_parameters_reports_user_and_model_kinds(fusion, call, mcp):
    fusion.add_parameter("width", "25 mm")
    fusion.design.modelParameters.add(
        "d1", values.ValueInput.createByReal(5.0), "cm", ""
    )
    payload = mcp.ok(call("list_parameters"))
    by_name = {entry["name"]: entry for entry in payload["parameters"]}
    assert payload["count"] == 2
    assert by_name["width"]["parameter_type"] == "user"
    assert by_name["width"]["expression"] == "25 mm"
    assert by_name["d1"]["parameter_type"] == "model"
    assert by_name["d1"]["driven"] is True
    assert by_name["width"]["driven"] is False


def test_list_parameters_requires_an_active_design(fusion_empty, call, mcp):
    assert "no active Fusion design" in mcp.error(call("list_parameters"))


def test_modify_parameter_updates_expression_and_recomputes(fusion, call, mcp):
    fusion.add_parameter("width", "25 mm")
    payload = mcp.ok(call("modify_parameter", name="width", expression="40 mm"))
    assert payload["expression"] == "40 mm"
    assert payload["value"] == 4.0
    assert payload["did_recompute"] is True
    assert payload["recomputed_feature_count"] == 0


def test_modify_parameter_unknown_name(fusion, call, mcp):
    message = mcp.error(call("modify_parameter", name="depth", expression="1 mm"))
    assert "no parameter named" in message


def test_modify_parameter_requires_an_active_design(fusion_empty, call, mcp):
    assert "no active Fusion design" in mcp.error(
        call("modify_parameter", name="w", expression="1 mm")
    )


def test_modify_parameter_reports_rejected_expression(fusion, monkeypatch, call, mcp):
    fusion.add_parameter("width", "25 mm")

    class _RejectingParameter:
        @property
        def expression(self):
            return "25 mm"

        @expression.setter
        def expression(self, value):
            raise RuntimeError("invalid expression")

    monkeypatch.setattr(
        fusion.user_parameters, "itemByName", lambda name: _RejectingParameter()
    )
    message = mcp.error(call("modify_parameter", name="width", expression="*"))
    assert "rejected the expression" in message


def test_parameter_expressions_resolve_other_parameters(fusion, call, mcp):
    fusion.add_parameter("width", "40 mm")
    fusion.add_parameter("half", "width / 2")
    parameter = fusion.user_parameters.itemByName("half")
    assert parameter.value == 2.0  # 40 mm -> 4.0 cm, halved


def test_parameter_unit_conversion_is_centimetre_internal(fusion, call, mcp):
    for expression, expected in (("10 mm", 1.0), ("1 cm", 1.0), ("1 m", 100.0), ("1 in", 2.54)):
        fusion.add_parameter(f"p_{expected}_{expression.replace(' ', '_')}", expression)
        parameter = fusion.user_parameters.itemByName(
            f"p_{expected}_{expression.replace(' ', '_')}"
        )
        assert parameter.value == expected, expression
