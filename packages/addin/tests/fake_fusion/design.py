"""Fake design: components, parameters with a real expression engine, timeline,
export manager, and the computeAll recompute path."""

from __future__ import annotations

import ast
import math
import os
import re

from . import values
from .features import FakeBRepBodies, FakeFeatures
from .geometry import FakeSketches

# ── Expression evaluation ────────────────────────────────────────────────────
# Fusion expressions ("25 mm", "width / 2", "45 deg") are consumed by the
# built-in expression engine.  The fake evaluates them to a number in the
# parameter's *internal* unit (cm for length, degrees for angle), which is what
# Parameter.value reports in the real API.

_UNIT_FACTORS = {
    "mm": 0.1, "cm": 1.0, "m": 100.0, "meter": 100.0, "metre": 100.0,
    "in": 2.54, "inch": 2.54, "ft": 30.48, "foot": 30.48, "feet": 30.48,
    "deg": 1.0, "degree": 1.0, "degrees": 1.0,
    "rad": 180.0 / math.pi, "radian": 180.0 / math.pi, "radians": 180.0 / math.pi,
    "°": 1.0, "ul": 1.0, "unitless": 1.0,
}

_NUMBER_UNIT = re.compile(
    r"(?<![\w.])(\d*\.?\d+)\s*(mm|cm|in|ft|deg|rad|m|meter|metre|inch|foot|feet|"
    r"degree|degrees|radian|radians|ul|unitless|°)?\b"
)


def _fold_units(expression: str) -> str:
    """Replace ``<number> <unit>`` tokens with the value in internal units."""

    def convert(match):
        number = float(match.group(1))
        unit = match.group(2) or ""
        return repr(number * _UNIT_FACTORS.get(unit, 1.0))

    return _NUMBER_UNIT.sub(convert, expression)


def _eval_node(node, resolve):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, resolve)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        resolved = resolve(node.id)
        if resolved is None:
            raise KeyError(node.id)
        return float(resolved)
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left, resolve), _eval_node(node.right, resolve)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, resolve)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _eval_node(node.operand, resolve)
    raise ValueError(f"unsupported expression element: {ast.dump(node)}")


def evaluate_expression(expression, resolve):
    """Evaluate a Fusion expression string to a number in internal units.

    ``resolve(name)`` returns the value of a referenced parameter, or None.
    """
    if expression is None:
        raise ValueError("expression is required")
    folded = _fold_units(str(expression))
    if not folded.strip():
        raise ValueError("expression is empty")
    return _eval_node(ast.parse(folded, mode="eval"), resolve)


# ── Parameters ──────────────────────────────────────────────────────────────


class FakeParameter:
    def __init__(self, name, expression, unit, is_driven, design):
        self.name = name
        self._expression = str(expression)
        self.unit = unit or ""
        self.isDriven = is_driven
        self._design = design

    @property
    def expression(self):
        return self._expression

    @expression.setter
    def expression(self, value):
        self._expression = str(value)
        self._design._mark_dirty()

    @property
    def value(self):
        return evaluate_expression(self._expression, self._design._resolve_parameter)


class _Parameters:
    """Shared user/model parameter collection behaviour."""

    def __init__(self, design, is_driven):
        self._design = design
        self._is_driven = is_driven
        self._items: list[FakeParameter] = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def itemByName(self, name):
        for parameter in self._items:
            if parameter.name == name:
                return parameter
        return None

    def add(self, name, value_input, unit="", comment=""):
        del comment
        if self.itemByName(name) is not None:
            raise ValueError(f"a parameter named '{name}' already exists")
        expression = getattr(value_input, "expression", None)
        if expression is None:
            real = getattr(value_input, "real", 0.0)
            expression = repr(float(real))
        parameter = FakeParameter(name, expression, unit, self._is_driven, self._design)
        self._items.append(parameter)
        self._design._mark_dirty()
        return parameter

    def __iter__(self):
        return iter(self._items)


class FakeUserParameters(_Parameters):
    def __init__(self, design):
        super().__init__(design, is_driven=False)


class FakeModelParameters(_Parameters):
    def __init__(self, design):
        super().__init__(design, is_driven=True)


# ── Timeline ────────────────────────────────────────────────────────────────


class FakeTimeline:
    def __init__(self):
        self._features: list = []

    @property
    def count(self):
        return len(self._features)

    @property
    def markerIndex(self):
        # The edit marker sits just past the last feature.
        return len(self._features)

    def item(self, index):
        return self._features[index] if 0 <= index < len(self._features) else None

    def _append_feature(self, feature):
        self._features.append(feature)
        feature.timelineIndex = len(self._features) - 1


# ── Units and export ────────────────────────────────────────────────────────


class FakeUnitsManager:
    def __init__(self, default_length_units="cm", display_units=None):
        self.defaultLengthUnits = default_length_units
        self.distanceDisplayUnits = display_units


class FakeExportOptions:
    def __init__(self, filename, root=None):
        self.filename = filename
        self.root = root
        self.meshRefinement = values.MeshRefinementSettings.MeshRefinementMedium
        self.unitType = values.DistanceUnits.CentimeterDistanceUnits


class FakeExportManager:
    def __init__(self, design):
        self._design = design

    def _options(self, path, root=None):
        return FakeExportOptions(path, root if root is not None else self._design.rootComponent)

    def createSTEPExportOptions(self, path):
        return self._options(path)

    def createIGESExportOptions(self, path):
        return self._options(path)

    def createFusionArchiveExportOptions(self, path):
        return self._options(path)

    def createOBJExportOptions(self, root, path):
        return self._options(path, root)

    def createSTLExportOptions(self, root, path):
        return self._options(path, root)

    def createPDFExportOptions(self, path):
        return self._options(path)

    def execute(self, options):
        # Write a real file so size_bytes is observable, like the real export.
        directory = os.path.dirname(options.filename or "")
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(options.filename, "wb") as handle:
            handle.write(b"FAKE EXPORT %s\n" % type(options).__name__.encode())
        return True


# ── Component and design ────────────────────────────────────────────────────


class FakeComponent:
    def __init__(self, name="Component1", design=None):
        self.name = name
        self.design = design
        self.sketches = FakeSketches()
        self.features = FakeFeatures(design.timeline if design else FakeTimeline())
        self.bodies = FakeBRepBodies()
        self.occurrences = FakeOccurrences()


class FakeOccurrences:
    def __init__(self):
        self._items: list = []

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def add(self, component, name="Occurrence1"):
        occurrence = FakeOccurrence(component, name)
        self._items.append(occurrence)
        return occurrence

    def __iter__(self):
        return iter(self._items)


class FakeOccurrence:
    def __init__(self, component, name):
        self.component = component
        self.name = name
        self.isVisible = True

    @property
    def objectType(self):
        return "adsk.fusion.Occurrence"


class FakeDesign:
    """``adsk.fusion.Design``: the product of a design document."""

    def __init__(self, timeline=None):
        self.designType = values.DesignTypes.ParametricDesignType
        self.unitsManager = FakeUnitsManager()
        self.fusionUnitsManager = FakeUnitsManager()
        self._timeline = timeline or FakeTimeline()
        self._root = FakeComponent("Root Component", self)
        self.userParameters = FakeUserParameters(self)
        self.modelParameters = FakeModelParameters(self)
        self.exportManager = FakeExportManager(self)
        self._dirty = False
        self.recomputedFeatureCount = None

    # -- static wrapper method --------------------------------------------

    @staticmethod
    def cast(product):
        # The real wrapper returns a typed handle or None for a non-design.
        return product if isinstance(product, FakeDesign) else None

    # -- structure --------------------------------------------------------

    @property
    def rootComponent(self):
        return self._root

    @property
    def timeline(self):
        # Direct modeling has no timeline; the tools read it through safe_get.
        if self.designType == values.DesignTypes.DirectDesignType:
            return None
        return self._timeline

    # -- parameter resolution used by the expression engine ----------------

    def _resolve_parameter(self, name):
        for collection in (self.userParameters, self.modelParameters):
            parameter = collection.itemByName(name)
            if parameter is not None:
                return parameter.value
        return None

    def _mark_dirty(self):
        self._dirty = True

    # -- recompute --------------------------------------------------------

    def computeAll(self):
        """Re-evaluate the whole timeline; report how many features moved."""
        changed = self._root.features._recompute_all()
        self.recomputedFeatureCount = changed
        self._dirty = False
        # Recomputing leaves the edit marker at the end of the timeline.
        for index, feature in enumerate(self._timeline._features):
            feature.timelineIndex = index
        return True
