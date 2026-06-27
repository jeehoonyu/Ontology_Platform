"""
Foundry FUSION (deepening module) — spreadsheets, a deterministic formula engine,
and ontology object-set references materialized into cell ranges.

This module is a self-contained APIRouter. Every ORM class name and __tablename__
is prefixed with "Fus"/"fus_" so it does not collide on the shared SQLAlchemy Base.

Docs read (Palantir Foundry Fusion) — captured before coding:
  - https://www.palantir.com/docs/foundry/fusion/overview
  - https://www.palantir.com/docs/foundry/fusion/formulas-overview
  - https://www.palantir.com/docs/foundry/fusion/sheets-overview
  - https://www.palantir.com/docs/foundry/fusion/function-library
  - https://www.palantir.com/docs/foundry/fusion/lookup-datasets
  - https://www.palantir.com/docs/foundry/fusion/find-and-use-data
  - https://www.palantir.com/docs/foundry/fusion/perform-actions

Documented mechanics honored here:
  * Type "=" into a cell to enter a formula (formulas-overview).
  * Cell references: A1, range A1:A3, cross-sheet Sheet2!A1:A3 (sheets-overview).
  * String literals use SINGLE quotes in Fusion (sheets-overview); we also accept
    double quotes for ergonomics.
  * Function library is a superset of Contour DSL + spreadsheet functions; we
    implement the documented core deterministically: math/aggregation (SUM, AVG,
    AVERAGE, MIN, MAX, COUNT, ROUND, ABS, plus a few), logical (IF, AND, OR, NOT,
    IFERROR), string (CONCAT), and arithmetic with parentheses (function-library).
  * Foundry data is imported via lookup/object-set materialization into a cell
    range; projected property columns become literals usable by formulas
    (lookup-datasets, find-and-use-data, perform-actions get_property).

Deterministic by design: no real network, no randomness. Errors propagate as
spreadsheet error tokens (#REF!, #DIV/0!, #CYCLE!, #NAME?, #VALUE!, #ERR!).
"""

from .database import Base, get_db
from . import models, models_action
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
import time, uuid, re

router = APIRouter(tags=["fusion"])

# Spreadsheet error tokens (mirrors Fusion/standard spreadsheet error semantics).
ERROR_TOKENS = {"#REF!", "#DIV/0!", "#CYCLE!", "#NAME?", "#VALUE!", "#ERR!", "#N/A"}


# ---------------------------------------------------------------------------
# SQLAlchemy models (all prefixed Fus / fus_)
# ---------------------------------------------------------------------------

class FusWorkbook(Base):
    __tablename__ = "fus_workbooks"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    owner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class FusSheet(Base):
    __tablename__ = "fus_sheets"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    workbook_id: Mapped[str] = mapped_column(String, ForeignKey("fus_workbooks.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(Integer)


class FusCell(Base):
    __tablename__ = "fus_cells"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    sheet_id: Mapped[str] = mapped_column(String, ForeignKey("fus_sheets.id"), index=True)
    ref: Mapped[str] = mapped_column(String, index=True)   # A1 notation
    raw: Mapped[str] = mapped_column(String)               # literal or "=formula"
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


class FusReference(Base):
    __tablename__ = "fus_references"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    sheet_id: Mapped[str] = mapped_column(String, ForeignKey("fus_sheets.id"), index=True)
    anchor_ref: Mapped[str] = mapped_column(String)        # top-left of materialized range
    object_type_id: Mapped[str] = mapped_column(String)
    property_columns: Mapped[list] = mapped_column(JSON, default=list)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WorkbookCreate(BaseModel):
    id: Optional[str] = None
    display_name: str
    owner: Optional[str] = None


class WorkbookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    owner: Optional[str] = None
    created_at: int
    updated_at: int


class SheetCreate(BaseModel):
    id: Optional[str] = None
    workbook_id: str
    name: str


class SheetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workbook_id: str
    name: str
    created_at: int


class CellSpec(BaseModel):
    ref: str
    raw: str


class CellsBulkSet(BaseModel):
    cells: List[CellSpec]


class CellRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sheet_id: str
    ref: str
    raw: str


class StatelessEvalRequest(BaseModel):
    cells: Dict[str, str]   # ref -> raw


class ReferenceCreate(BaseModel):
    anchor_ref: str
    object_type_id: str
    property_columns: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    include_header: bool = False


# ---------------------------------------------------------------------------
# A1 reference helpers (col letters <-> 0-based index; rows 1-based)
# ---------------------------------------------------------------------------

_A1_RE = re.compile(r"^\$?([A-Za-z]+)\$?([0-9]+)$")
_RANGE_RE = re.compile(r"^\$?([A-Za-z]+)\$?([0-9]+):\$?([A-Za-z]+)\$?([0-9]+)$")


def col_to_index(col: str) -> int:
    """'A'->0, 'B'->1, ..., 'Z'->25, 'AA'->26."""
    idx = 0
    for ch in col.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def index_to_col(idx: int) -> str:
    """0->'A', 25->'Z', 26->'AA'."""
    out = ""
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def parse_ref(ref: str):
    """Return (col_index, row_1based) for a single A1 ref, or None."""
    m = _A1_RE.match(ref.strip())
    if not m:
        return None
    return col_to_index(m.group(1)), int(m.group(2))


def expand_range(ref: str) -> Optional[List[str]]:
    """Expand 'A1:B3' into row-major list of single refs, or None if not a range."""
    m = _RANGE_RE.match(ref.strip())
    if not m:
        return None
    c1, r1 = col_to_index(m.group(1)), int(m.group(2))
    c2, r2 = col_to_index(m.group(3)), int(m.group(4))
    cmin, cmax = sorted((c1, c2))
    rmin, rmax = sorted((r1, r2))
    cells = []
    for r in range(rmin, rmax + 1):
        for c in range(cmin, cmax + 1):
            cells.append(f"{index_to_col(c)}{r}")
    return cells


def normalize_ref(ref: str) -> str:
    """Canonicalize a single A1 ref ('a1' -> 'A1'), stripping $ anchors."""
    p = parse_ref(ref)
    if not p:
        return ref.strip().upper()
    return f"{index_to_col(p[0])}{p[1]}"


# ---------------------------------------------------------------------------
# Formula tokenizer + recursive-descent parser
# ---------------------------------------------------------------------------

class FormulaError(Exception):
    def __init__(self, token: str):
        self.token = token
        super().__init__(token)


_TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<number>\d+\.\d+|\.\d+|\d+)
    | (?P<sqstring>'(?:[^']|'')*')
    | (?P<dqstring>"(?:[^"]|"")*")
    | (?P<range>\$?[A-Za-z]+\$?[0-9]+:\$?[A-Za-z]+\$?[0-9]+)
    | (?P<cell>\$?[A-Za-z]+\$?[0-9]+)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op><=|>=|<>|!=|==|[-+*/(),<>=])
    )
""", re.VERBOSE)


def tokenize(expr: str):
    tokens = []
    pos = 0
    n = len(expr)
    while pos < n:
        if expr[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            raise FormulaError("#ERR!")
        pos = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        tokens.append((kind, val.strip()))
    tokens.append(("end", ""))
    return tokens


class Parser:
    """Recursive-descent parser producing an AST of tuples.

    AST node forms:
      ("num", float) ("str", str) ("cell", ref) ("range", ref)
      ("bin", op, left, right) ("neg", node) ("func", name_lower, [args])
    """

    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, val):
        k, v = self.peek()
        if v != val:
            raise FormulaError("#ERR!")
        self.next()

    def parse(self):
        node = self.parse_comparison()
        if self.peek()[0] != "end":
            raise FormulaError("#ERR!")
        return node

    def parse_comparison(self):
        node = self.parse_add()
        while self.peek()[0] == "op" and self.peek()[1] in ("<", ">", "<=", ">=", "=", "==", "<>", "!="):
            op = self.next()[1]
            right = self.parse_add()
            node = ("bin", op, node, right)
        return node

    def parse_add(self):
        node = self.parse_mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            right = self.parse_mul()
            node = ("bin", op, node, right)
        return node

    def parse_mul(self):
        node = self.parse_unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.next()[1]
            right = self.parse_unary()
            node = ("bin", op, node, right)
        return node

    def parse_unary(self):
        if self.peek()[0] == "op" and self.peek()[1] == "-":
            self.next()
            return ("neg", self.parse_unary())
        if self.peek()[0] == "op" and self.peek()[1] == "+":
            self.next()
            return self.parse_unary()
        return self.parse_primary()

    def parse_primary(self):
        kind, val = self.peek()
        if kind == "number":
            self.next()
            return ("num", float(val))
        if kind == "sqstring":
            self.next()
            return ("str", val[1:-1].replace("''", "'"))
        if kind == "dqstring":
            self.next()
            return ("str", val[1:-1].replace('""', '"'))
        if kind == "range":
            self.next()
            return ("range", val)
        if kind == "ident":
            # function call OR a bare keyword (TRUE/FALSE)
            name = val
            self.next()
            if self.peek()[1] == "(":
                self.next()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.parse_comparison())
                    while self.peek()[1] == ",":
                        self.next()
                        args.append(self.parse_comparison())
                self.expect(")")
                return ("func", name.lower(), args)
            low = name.lower()
            if low == "true":
                return ("num", 1.0)  # booleans modeled numerically; rendered later
            if low == "false":
                return ("num", 0.0)
            raise FormulaError("#NAME?")
        if kind == "cell":
            self.next()
            return ("cell", val)
        if kind == "op" and val == "(":
            self.next()
            node = self.parse_comparison()
            self.expect(")")
            return node
        raise FormulaError("#ERR!")


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_number(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if _is_number(v):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        if s in ERROR_TOKENS:
            raise FormulaError(s)
        try:
            return float(s)
        except ValueError:
            raise FormulaError("#VALUE!")
    if v is None:
        return 0.0
    raise FormulaError("#VALUE!")


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    if _is_number(v):
        return v != 0
    if isinstance(v, str):
        if v in ERROR_TOKENS:
            raise FormulaError(v)
        return v.strip().lower() not in ("", "false", "0")
    return bool(v)


def _to_str(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if _is_number(v):
        if float(v).is_integer():
            return str(int(v))
        return repr(float(v))
    if v is None:
        return ""
    return str(v)


class Evaluator:
    """Evaluates an AST against a cell environment with cycle detection.

    `cell_values` maps normalized ref -> resolved python value (computed lazily).
    `cell_asts` maps normalized ref -> ("formula", ast) | ("literal", value).
    """

    def __init__(self, cell_asts: Dict[str, Any], lookup_source=None):
        self.cell_asts = cell_asts
        self.cache: Dict[str, Any] = {}
        self.in_progress = set()
        # Optional callable(dataset_id, value_field, key_field, key_value) -> first
        # matching value (or "#N/A"). Lets formulas embed LOOKUP() against a
        # DataAsset (lookup-datasets). When unset, LOOKUP() resolves to #N/A.
        self.lookup_source = lookup_source

    def resolve_cell(self, ref: str):
        ref = normalize_ref(ref)
        if ref in self.cache:
            val = self.cache[ref]
            if isinstance(val, str) and val in ERROR_TOKENS:
                raise FormulaError(val)
            return val
        if ref in self.in_progress:
            raise FormulaError("#CYCLE!")
        if ref not in self.cell_asts:
            return ""  # empty cell -> empty
        self.in_progress.add(ref)
        try:
            kind, payload = self.cell_asts[ref]
            if kind == "literal":
                val = payload
            else:
                val = self.eval(payload)
        except FormulaError as fe:
            val = fe.token
            self.cache[ref] = val
            self.in_progress.discard(ref)
            raise
        self.cache[ref] = val
        self.in_progress.discard(ref)
        return val

    def collect_range(self, range_ref: str) -> List[Any]:
        refs = expand_range(range_ref)
        if refs is None:
            raise FormulaError("#REF!")
        out = []
        for r in refs:
            out.append(self.resolve_cell(r))
        return out

    def _flatten_args(self, args) -> List[Any]:
        """Evaluate args, expanding ranges into their member values."""
        out = []
        for a in args:
            if a[0] == "range":
                out.extend(self.collect_range(a[1]))
            else:
                out.append(self.eval(a))
        return out

    def _numeric_values(self, args) -> List[float]:
        """Like _flatten_args but numbers-only (skip empty/blank, error on bad)."""
        nums = []
        for v in self._flatten_args(args):
            if v == "" or v is None:
                continue
            if isinstance(v, str) and v in ERROR_TOKENS:
                raise FormulaError(v)
            nums.append(_to_number(v))
        return nums

    def eval(self, node):
        tag = node[0]
        if tag == "num":
            return node[1]
        if tag == "str":
            return node[1]
        if tag == "cell":
            return self.resolve_cell(node[1])
        if tag == "range":
            # A bare range used as a scalar is an error.
            raise FormulaError("#VALUE!")
        if tag == "neg":
            return -_to_number(self.eval(node[1]))
        if tag == "bin":
            return self._eval_bin(node[1], node[2], node[3])
        if tag == "func":
            return self._eval_func(node[1], node[2])
        raise FormulaError("#ERR!")

    def _eval_bin(self, op, left, right):
        lv = self.eval(left)
        rv = self.eval(right)
        if op in ("+", "-", "*", "/"):
            a, b = _to_number(lv), _to_number(rv)
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                if b == 0:
                    raise FormulaError("#DIV/0!")
                return a / b
        # comparisons -> boolean
        if op in ("=", "=="):
            return self._cmp_eq(lv, rv)
        if op in ("<>", "!="):
            return not self._cmp_eq(lv, rv)
        # ordered comparisons
        if _is_number(lv) or _is_number(rv) or isinstance(lv, bool) or isinstance(rv, bool):
            a, b = _to_number(lv), _to_number(rv)
        else:
            a, b = _to_str(lv), _to_str(rv)
        if op == "<":
            return a < b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        if op == ">=":
            return a >= b
        raise FormulaError("#ERR!")

    @staticmethod
    def _cmp_eq(lv, rv) -> bool:
        if (_is_number(lv) or isinstance(lv, bool)) and (_is_number(rv) or isinstance(rv, bool)):
            return _to_number(lv) == _to_number(rv)
        return _to_str(lv) == _to_str(rv)

    def _eval_func(self, name, args):
        # --- aggregation / math over ranges ---
        if name == "sum":
            return sum(self._numeric_values(args))
        if name in ("average", "avg", "mean"):
            nums = self._numeric_values(args)
            if not nums:
                raise FormulaError("#DIV/0!")
            return sum(nums) / len(nums)
        if name == "min":
            nums = self._numeric_values(args)
            if not nums:
                raise FormulaError("#VALUE!")
            return min(nums)
        if name == "max":
            nums = self._numeric_values(args)
            if not nums:
                raise FormulaError("#VALUE!")
            return max(nums)
        if name == "count":
            # count numeric items (function-library: count_numeric semantics for COUNT of numbers)
            return float(len(self._numeric_values(args)))
        if name == "product":
            nums = self._numeric_values(args)
            out = 1.0
            for n in nums:
                out *= n
            return out
        if name == "median":
            nums = sorted(self._numeric_values(args))
            if not nums:
                raise FormulaError("#VALUE!")
            mid = len(nums) // 2
            if len(nums) % 2:
                return nums[mid]
            return (nums[mid - 1] + nums[mid]) / 2

        # --- single-number math ---
        if name == "abs":
            self._arity(args, 1)
            return abs(_to_number(self.eval(args[0])))
        if name == "round":
            if len(args) not in (1, 2):
                raise FormulaError("#ERR!")
            x = _to_number(self.eval(args[0]))
            ndigits = int(_to_number(self.eval(args[1]))) if len(args) == 2 else 0
            # banker's-rounding-free, deterministic half-up
            return self._round_half_up(x, ndigits)
        if name == "floor":
            self._arity(args, 1)
            import math
            return float(math.floor(_to_number(self.eval(args[0]))))
        if name == "ceil":
            self._arity(args, 1)
            import math
            return float(math.ceil(_to_number(self.eval(args[0]))))
        if name == "sqrt":
            self._arity(args, 1)
            x = _to_number(self.eval(args[0]))
            if x < 0:
                raise FormulaError("#VALUE!")
            return x ** 0.5
        if name == "pow":
            self._arity(args, 2)
            return _to_number(self.eval(args[0])) ** _to_number(self.eval(args[1]))

        # --- logical ---
        if name == "if":
            if len(args) not in (2, 3):
                raise FormulaError("#ERR!")
            cond = _truthy(self.eval(args[0]))
            if cond:
                return self.eval(args[1])
            return self.eval(args[2]) if len(args) == 3 else False
        if name == "and":
            vals = self._flatten_args(args)
            if not vals:
                raise FormulaError("#ERR!")
            return all(_truthy(v) for v in vals)
        if name == "or":
            vals = self._flatten_args(args)
            if not vals:
                raise FormulaError("#ERR!")
            return any(_truthy(v) for v in vals)
        if name == "not":
            self._arity(args, 1)
            return not _truthy(self.eval(args[0]))
        if name == "iferror":
            self._arity(args, 2)
            try:
                return self.eval(args[0])
            except FormulaError:
                return self.eval(args[1])
        if name == "coalesce":
            for a in args:
                v = self.eval(a)
                if v not in ("", None):
                    return v
            return ""
        if name == "isnull":
            self._arity(args, 1)
            v = self.eval(args[0])
            return v in ("", None)

        # --- string ---
        if name in ("concat", "concatenate"):
            return "".join(_to_str(v) for v in self._flatten_args(args))
        if name == "concat_ws":
            vals = self._flatten_args(args)
            if not vals:
                raise FormulaError("#ERR!")
            sep = _to_str(vals[0])
            return sep.join(_to_str(v) for v in vals[1:])
        if name == "upper":
            self._arity(args, 1)
            return _to_str(self.eval(args[0])).upper()
        if name == "lower":
            self._arity(args, 1)
            return _to_str(self.eval(args[0])).lower()
        if name == "length":
            self._arity(args, 1)
            return float(len(_to_str(self.eval(args[0]))))
        if name == "trim":
            self._arity(args, 1)
            return _to_str(self.eval(args[0])).strip()
        if name == "left":
            self._arity(args, 2)
            s = _to_str(self.eval(args[0]))
            return s[: int(_to_number(self.eval(args[1])))]
        if name == "right":
            self._arity(args, 2)
            s = _to_str(self.eval(args[0]))
            k = int(_to_number(self.eval(args[1])))
            return s[-k:] if k > 0 else ""

        # --- data lookup (Fusion lookup-datasets) ---
        # LOOKUP(dataset_id, value_field, key_field, key_value) -> first match.
        if name == "lookup":
            self._arity(args, 4)
            if self.lookup_source is None:
                return "#N/A"
            dataset_id = _to_str(self.eval(args[0]))
            value_field = _to_str(self.eval(args[1]))
            key_field = _to_str(self.eval(args[2]))
            key_value = self.eval(args[3])
            result = self.lookup_source(dataset_id, value_field, key_field, key_value)
            return "#N/A" if result is None else result

        raise FormulaError("#NAME?")

    @staticmethod
    def _arity(args, n):
        if len(args) != n:
            raise FormulaError("#ERR!")

    @staticmethod
    def _round_half_up(x: float, ndigits: int) -> float:
        import math
        factor = 10 ** ndigits
        if x >= 0:
            r = math.floor(x * factor + 0.5) / factor
        else:
            r = math.ceil(x * factor - 0.5) / factor
        return r if ndigits > 0 else float(r)


# ---------------------------------------------------------------------------
# Core engine: build cell ASTs and evaluate a whole sheet's worth of cells
# ---------------------------------------------------------------------------

def _parse_literal(raw: str):
    """Interpret a non-formula raw cell value as number / string / bool."""
    s = raw.strip()
    if s == "":
        return ""
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if s in ERROR_TOKENS:
        return s
    try:
        if re.fullmatch(r"-?\d+", s):
            return float(int(s))
        return float(s)
    except ValueError:
        pass
    # quoted literal?
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def build_cell_asts(raw_by_ref: Dict[str, str]) -> Dict[str, Any]:
    """raw_by_ref: ref -> raw string. Returns ref -> ('literal', val) | ('formula', ast)."""
    out: Dict[str, Any] = {}
    for ref, raw in raw_by_ref.items():
        nref = normalize_ref(ref)
        if raw is None:
            raw = ""
        if isinstance(raw, str) and raw.startswith("="):
            expr = raw[1:]
            try:
                ast = Parser(tokenize(expr)).parse()
                out[nref] = ("formula", ast)
            except FormulaError as fe:
                out[nref] = ("literal", fe.token)
        else:
            out[nref] = ("literal", _parse_literal(str(raw)))
    return out


def evaluate_cells(raw_by_ref: Dict[str, str], lookup_source=None) -> Dict[str, Any]:
    """Return ref -> computed value (errors as tokens). Renders booleans as TRUE/FALSE.

    `lookup_source`, if supplied, enables the LOOKUP() formula function to pull a
    first matching value from a DataAsset (Fusion lookup-datasets).
    """
    asts = build_cell_asts(raw_by_ref)
    ev = Evaluator(asts, lookup_source=lookup_source)
    result: Dict[str, Any] = {}
    for ref in asts.keys():
        try:
            val = ev.resolve_cell(ref)
        except FormulaError as fe:
            val = fe.token
        # render booleans deterministically as TRUE/FALSE strings
        if isinstance(val, bool):
            val = "TRUE" if val else "FALSE"
        elif _is_number(val) and float(val).is_integer():
            val = int(val)
        result[ref] = val
    return result


# ---------------------------------------------------------------------------
# Endpoints — Workbooks
# ---------------------------------------------------------------------------

@router.post("/fusion/workbooks", response_model=WorkbookRead)
def create_workbook(body: WorkbookCreate, db: Session = Depends(get_db)):
    wid = body.id or uuid.uuid4().hex
    if db.query(FusWorkbook).filter(FusWorkbook.id == wid).first():
        raise HTTPException(status_code=400, detail="FusWorkbook already exists")
    now = int(time.time())
    row = FusWorkbook(id=wid, display_name=body.display_name, owner=body.owner,
                      created_at=now, updated_at=now)
    db.add(row)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system",
        event_type="fusion.workbook.created", subject_type="fus_workbook",
        subject_id=wid, payload={"display_name": body.display_name}))
    db.commit()
    db.refresh(row)
    return row


@router.get("/fusion/workbooks", response_model=List[WorkbookRead])
def list_workbooks(db: Session = Depends(get_db)):
    return db.query(FusWorkbook).order_by(FusWorkbook.created_at).all()


# ---------------------------------------------------------------------------
# Endpoints — Sheets
# ---------------------------------------------------------------------------

@router.post("/fusion/sheets", response_model=SheetRead)
def create_sheet(body: SheetCreate, db: Session = Depends(get_db)):
    if not db.query(FusWorkbook).filter(FusWorkbook.id == body.workbook_id).first():
        raise HTTPException(status_code=404, detail="FusWorkbook not found")
    sid = body.id or uuid.uuid4().hex
    if db.query(FusSheet).filter(FusSheet.id == sid).first():
        raise HTTPException(status_code=400, detail="FusSheet already exists")
    row = FusSheet(id=sid, workbook_id=body.workbook_id, name=body.name,
                   created_at=int(time.time()))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/fusion/workbooks/{workbook_id}/sheets", response_model=List[SheetRead])
def list_sheets(workbook_id: str, db: Session = Depends(get_db)):
    if not db.query(FusWorkbook).filter(FusWorkbook.id == workbook_id).first():
        raise HTTPException(status_code=404, detail="FusWorkbook not found")
    return db.query(FusSheet).filter(FusSheet.workbook_id == workbook_id).all()


# ---------------------------------------------------------------------------
# Endpoints — Cells
# ---------------------------------------------------------------------------

def _get_sheet(db: Session, sheet_id: str) -> FusSheet:
    sheet = db.query(FusSheet).filter(FusSheet.id == sheet_id).first()
    if not sheet:
        raise HTTPException(status_code=404, detail="FusSheet not found")
    return sheet


@router.put("/fusion/sheets/{sheet_id}/cells", response_model=List[CellRead])
def set_cells(sheet_id: str, body: CellsBulkSet, db: Session = Depends(get_db)):
    _get_sheet(db, sheet_id)
    now = int(time.time())
    out = []
    for spec in body.cells:
        nref = normalize_ref(spec.ref)
        if parse_ref(nref) is None:
            raise HTTPException(status_code=422, detail=f"Invalid cell ref '{spec.ref}'")
        existing = db.query(FusCell).filter(
            FusCell.sheet_id == sheet_id, FusCell.ref == nref).first()
        if existing:
            existing.raw = spec.raw
            existing.updated_at = now
            out.append(existing)
        else:
            cell = FusCell(id=uuid.uuid4().hex, sheet_id=sheet_id, ref=nref,
                           raw=spec.raw, created_at=now, updated_at=now)
            db.add(cell)
            out.append(cell)
    db.commit()
    for c in out:
        db.refresh(c)
    return out


@router.get("/fusion/sheets/{sheet_id}")
def get_sheet_cells(sheet_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    sheet = _get_sheet(db, sheet_id)
    cells = db.query(FusCell).filter(FusCell.sheet_id == sheet_id).all()
    return {
        "id": sheet.id,
        "name": sheet.name,
        "workbook_id": sheet.workbook_id,
        "cells": [{"ref": c.ref, "raw": c.raw} for c in cells],
    }


@router.post("/fusion/sheets/{sheet_id}/evaluate")
def evaluate_sheet(sheet_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _get_sheet(db, sheet_id)
    cells = db.query(FusCell).filter(FusCell.sheet_id == sheet_id).all()
    raw_by_ref = {c.ref: c.raw for c in cells}
    values = evaluate_cells(raw_by_ref, lookup_source=_make_lookup_source(db))
    return {
        "sheet_id": sheet_id,
        "values": values,
        "cells": [{"ref": c.ref, "raw": c.raw, "value": values.get(c.ref)} for c in cells],
    }


@router.post("/fusion/formula/evaluate")
def evaluate_formula_stateless(body: StatelessEvalRequest) -> Dict[str, Any]:
    """Quick stateless eval over an ad-hoc map of ref->raw."""
    raw_by_ref = {normalize_ref(k): v for k, v in body.cells.items()}
    values = evaluate_cells(raw_by_ref)
    return {"values": values}


# ---------------------------------------------------------------------------
# Endpoints — Ontology object-set references
# ---------------------------------------------------------------------------

def _matches_filters(props: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    for k, v in (filters or {}).items():
        if props.get(k) != v:
            return False
    return True


@router.post("/fusion/sheets/{sheet_id}/references")
def materialize_reference(sheet_id: str, body: ReferenceCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Materialize an object set (ObjectInstance query) into a cell range.

    Mirrors Fusion's lookup/object-import: query objects by object_type_id with
    optional equality filters, project property_columns, and write the resulting
    grid starting at anchor_ref. Each materialized cell becomes a literal usable
    by formulas (lookup-datasets / find-and-use-data).
    """
    _get_sheet(db, sheet_id)
    anchor = parse_ref(body.anchor_ref)
    if anchor is None:
        raise HTTPException(status_code=422, detail=f"Invalid anchor_ref '{body.anchor_ref}'")
    if not body.property_columns:
        raise HTTPException(status_code=422, detail="property_columns must not be empty")

    ot = db.query(models.ObjectType).filter(models.ObjectType.id == body.object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"ObjectType '{body.object_type_id}' not found")

    instances = db.query(models.ObjectInstance).filter(
        models.ObjectInstance.object_type_id == body.object_type_id
    ).order_by(models.ObjectInstance.id).all()

    rows = [inst for inst in instances if _matches_filters(inst.properties or {}, body.filters)]

    anchor_col, anchor_row = anchor
    now = int(time.time())
    written: List[Dict[str, str]] = []

    def _write(col_idx: int, row_1based: int, value: Any):
        ref = f"{index_to_col(col_idx)}{row_1based}"
        raw = "" if value is None else str(value)
        existing = db.query(FusCell).filter(
            FusCell.sheet_id == sheet_id, FusCell.ref == ref).first()
        if existing:
            existing.raw = raw
            existing.updated_at = now
        else:
            db.add(FusCell(id=uuid.uuid4().hex, sheet_id=sheet_id, ref=ref,
                           raw=raw, created_at=now, updated_at=now))
        written.append({"ref": ref, "value": raw})

    cur_row = anchor_row
    if body.include_header:
        for ci, colname in enumerate(body.property_columns):
            _write(anchor_col + ci, cur_row, colname)
        cur_row += 1

    materialized_rows = 0
    for inst in rows:
        props = inst.properties or {}
        for ci, colname in enumerate(body.property_columns):
            _write(anchor_col + ci, cur_row, props.get(colname))
        cur_row += 1
        materialized_rows += 1

    ref_row = FusReference(
        id=uuid.uuid4().hex, sheet_id=sheet_id, anchor_ref=normalize_ref(body.anchor_ref),
        object_type_id=body.object_type_id, property_columns=body.property_columns,
        filters=body.filters or {}, created_at=now,
    )
    db.add(ref_row)
    db.add(models_action.AuditLog(id=uuid.uuid4().hex, actor="system",
        event_type="fusion.reference.materialized", subject_type="fus_reference",
        subject_id=ref_row.id,
        payload={"object_type_id": body.object_type_id, "rows": materialized_rows}))
    db.commit()

    last_col = index_to_col(anchor_col + len(body.property_columns) - 1)
    end_row = cur_row - 1
    return {
        "reference_id": ref_row.id,
        "sheet_id": sheet_id,
        "anchor_ref": ref_row.anchor_ref,
        "object_type_id": body.object_type_id,
        "property_columns": body.property_columns,
        "rows_materialized": materialized_rows,
        "range": f"{normalize_ref(body.anchor_ref)}:{last_col}{end_row}" if materialized_rows or body.include_header else None,
        "written_cells": written,
    }


@router.get("/fusion/sheets/{sheet_id}/references")
def list_references(sheet_id: str, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    _get_sheet(db, sheet_id)
    refs = db.query(FusReference).filter(FusReference.sheet_id == sheet_id).all()
    return [
        {
            "id": r.id, "anchor_ref": r.anchor_ref, "object_type_id": r.object_type_id,
            "property_columns": r.property_columns, "filters": r.filters,
        }
        for r in refs
    ]


# ===========================================================================
# LOOKUP family over a DataAsset's records (Fusion lookup-datasets)
# ===========================================================================
#
# Fusion lookup formulas (lookup / lookup_array / lookup_distinct /
# lookup_dropdown / lookup_sorted / lookup_schema) pull live values from a
# dataset column, filtered by (column, value) pairs. Here the "dataset" is a
# DataAsset.records list-of-dicts (or a table passed inline in the request).
# All endpoints are deterministic and capped at FUS_LOOKUP_LIMIT results
# (docs: "Lookups are limited to 2,000 results").

FUS_LOOKUP_LIMIT = 2000


def _coerce_lookup_value(v: Any) -> Any:
    """Normalize a key for comparison so 1 == "1" and 1.0 == 1 like Fusion cells."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, str):
        s = v.strip()
        try:
            f = float(s)
            return int(f) if f.is_integer() else f
        except ValueError:
            return s
    return v


def _resolve_lookup_records(
    db: Session,
    dataset_id: Optional[str],
    table: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return the record list for a LOOKUP: an inline `table`, else a DataAsset's
    records. Raises 404 if neither resolves to data."""
    if table is not None:
        return [dict(r) for r in table]
    if dataset_id is None:
        raise HTTPException(status_code=422, detail="dataset_id or table is required")
    asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"DataAsset '{dataset_id}' not found")
    return [dict(r) for r in (asset.records or [])]


def _filtered_records(
    records: List[Dict[str, Any]],
    key_field: Optional[str],
    key_value: Any,
    extra_filters: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Apply an optional (key_field == key_value) match plus extra equality filters.
    Matching is value-coerced so cell strings and numbers compare consistently."""
    out = records
    if key_field is not None:
        target = _coerce_lookup_value(key_value)
        out = [r for r in out if _coerce_lookup_value(r.get(key_field)) == target]
    for fk, fv in (extra_filters or {}).items():
        tv = _coerce_lookup_value(fv)
        out = [r for r in out if _coerce_lookup_value(r.get(fk)) == tv]
    return out


def _infer_column_type(values: List[Any]) -> str:
    """Infer a Foundry-style base type from a column's sampled values."""
    seen = [v for v in values if v is not None]
    if not seen:
        return "string"
    if all(isinstance(v, bool) for v in seen):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in seen):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in seen):
        return "double"
    return "string"


def _make_lookup_source(db: Session):
    """Build a callable usable by the formula evaluator's LOOKUP() function:
    lookup_source(dataset_id, value_field, key_field, key_value) -> first match | None."""
    def _source(dataset_id: str, value_field: str, key_field: str, key_value: Any):
        asset = db.query(models.DataAsset).filter(models.DataAsset.id == dataset_id).first()
        if not asset:
            return None
        matches = _filtered_records(list(asset.records or []), key_field, key_value, None)
        for r in matches:
            if value_field in r:
                return r.get(value_field)
        return None
    return _source


# ---------------------------------------------------------------------------
# LOOKUP request/response schemas
# ---------------------------------------------------------------------------

class LookupRequest(BaseModel):
    dataset_id: Optional[str] = None
    table: Optional[List[Dict[str, Any]]] = None
    key_field: str
    key_value: Any = None
    value_field: str
    filters: Dict[str, Any] = Field(default_factory=dict)


class LookupArrayRequest(BaseModel):
    dataset_id: Optional[str] = None
    table: Optional[List[Dict[str, Any]]] = None
    key_field: str
    key_value: Any = None
    value_field: str
    filters: Dict[str, Any] = Field(default_factory=dict)


class LookupDistinctRequest(BaseModel):
    dataset_id: Optional[str] = None
    table: Optional[List[Dict[str, Any]]] = None
    value_field: str
    key_field: Optional[str] = None
    key_value: Any = None
    filters: Dict[str, Any] = Field(default_factory=dict)


class LookupDropdownRequest(BaseModel):
    dataset_id: Optional[str] = None
    table: Optional[List[Dict[str, Any]]] = None
    field: str
    filters: Dict[str, Any] = Field(default_factory=dict)


class LookupSortedRequest(BaseModel):
    dataset_id: Optional[str] = None
    table: Optional[List[Dict[str, Any]]] = None
    value_field: str
    sort_field: str
    desc: bool = False
    key_field: Optional[str] = None
    key_value: Any = None
    filters: Dict[str, Any] = Field(default_factory=dict)


class LookupSchemaRequest(BaseModel):
    dataset_id: Optional[str] = None
    table: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# LOOKUP endpoints
# ---------------------------------------------------------------------------

@router.post("/fusion/lookup")
def fusion_lookup(body: LookupRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """First value of `value_field` where `key_field == key_value` (LOOKUP).
    Returns found=False / value=#N/A when nothing matches."""
    records = _resolve_lookup_records(db, body.dataset_id, body.table)
    matches = _filtered_records(records, body.key_field, body.key_value, body.filters)
    for r in matches:
        if body.value_field in r:
            return {"found": True, "value": r.get(body.value_field), "match_count": len(matches)}
    return {"found": False, "value": "#N/A", "match_count": 0}


@router.post("/fusion/lookup-array")
def fusion_lookup_array(body: LookupArrayRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """All `value_field` values where `key_field == key_value` (LOOKUP_ARRAY)."""
    records = _resolve_lookup_records(db, body.dataset_id, body.table)
    matches = _filtered_records(records, body.key_field, body.key_value, body.filters)
    values = [r.get(body.value_field) for r in matches if body.value_field in r]
    truncated = len(values) > FUS_LOOKUP_LIMIT
    return {
        "values": values[:FUS_LOOKUP_LIMIT],
        "count": min(len(values), FUS_LOOKUP_LIMIT),
        "truncated": truncated,
    }


@router.post("/fusion/lookup-distinct")
def fusion_lookup_distinct(body: LookupDistinctRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Deduplicated `value_field` values (LOOKUP_DISTINCT), order preserved."""
    records = _resolve_lookup_records(db, body.dataset_id, body.table)
    matches = _filtered_records(records, body.key_field, body.key_value, body.filters)
    seen = []
    seen_keys = set()
    for r in matches:
        if body.value_field not in r:
            continue
        v = r.get(body.value_field)
        key = _coerce_lookup_value(v) if not isinstance(v, (dict, list)) else repr(v)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        seen.append(v)
        if len(seen) >= FUS_LOOKUP_LIMIT:
            break
    return {"values": seen, "count": len(seen)}


@router.post("/fusion/lookup-dropdown")
def fusion_lookup_dropdown(body: LookupDropdownRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Distinct, sorted choice list for `field` (LOOKUP_DROPDOWN)."""
    records = _resolve_lookup_records(db, body.dataset_id, body.table)
    matches = _filtered_records(records, None, None, body.filters)
    seen_keys = set()
    choices = []
    for r in matches:
        if body.field not in r:
            continue
        v = r.get(body.field)
        key = _coerce_lookup_value(v) if not isinstance(v, (dict, list)) else repr(v)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        choices.append(v)
    try:
        choices = sorted(choices, key=lambda x: (x is None, _to_str(x)))
    except TypeError:
        pass
    choices = choices[:FUS_LOOKUP_LIMIT]
    return {"field": body.field, "choices": choices, "count": len(choices)}


@router.post("/fusion/lookup-sorted")
def fusion_lookup_sorted(body: LookupSortedRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """`value_field` values sorted by `sort_field` ascending (or desc) (LOOKUP_SORTED)."""
    records = _resolve_lookup_records(db, body.dataset_id, body.table)
    matches = _filtered_records(records, body.key_field, body.key_value, body.filters)

    def _sort_key(r):
        v = r.get(body.sort_field)
        if v is None:
            return (1, 0.0, "")
        if isinstance(v, bool):
            return (0, float(v), "")
        if isinstance(v, (int, float)):
            return (0, float(v), "")
        return (0, 0.0, _to_str(v))

    ordered = sorted(matches, key=_sort_key, reverse=body.desc)
    values = [r.get(body.value_field) for r in ordered if body.value_field in r]
    values = values[:FUS_LOOKUP_LIMIT]
    return {
        "values": values,
        "count": len(values),
        "sort_field": body.sort_field,
        "desc": body.desc,
    }


@router.post("/fusion/lookup-schema")
def fusion_lookup_schema(body: LookupSchemaRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Column names + inferred base types from a dataset's records (LOOKUP_SCHEMA)."""
    records = _resolve_lookup_records(db, body.dataset_id, body.table)
    columns: List[str] = []
    seen = set()
    for r in records:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                columns.append(k)
    schema = [
        {"name": col, "type": _infer_column_type([r.get(col) for r in records if col in r])}
        for col in columns
    ]
    return {"columns": columns, "schema": schema, "record_count": len(records)}


# ===========================================================================
# Action WRITE-BACK: stage ObjectInstance updates from computed cells
# ===========================================================================
#
# Fusion can submit/write computed sheet values back to the data model
# (perform-actions). Here a write-back evaluates the sheet, then for each row
# mapping projects computed cell values onto an ObjectInstance's properties.
# Staged changes are returned for review; they are only persisted when
# commit=true (mirrors Fusion's stage-then-submit action flow).

class WriteBackRowMapping(BaseModel):
    object_id: str
    # property_name -> cell ref (A1) whose computed value is written
    cells: Dict[str, str] = Field(default_factory=dict)


class WriteBackRequest(BaseModel):
    target_object_type_id: str
    row_mappings: List[WriteBackRowMapping]
    commit: bool = False


@router.post("/fusion/sheets/{sheet_id}/write-back")
def fusion_write_back(sheet_id: str, body: WriteBackRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Stage (and optionally commit) ObjectInstance property updates from computed
    cells. Each row mapping targets one ObjectInstance and maps property names to
    cell refs; the cell's evaluated value becomes the new property value."""
    _get_sheet(db, sheet_id)

    ot = db.query(models.ObjectType).filter(
        models.ObjectType.id == body.target_object_type_id).first()
    if not ot:
        raise HTTPException(status_code=404,
                            detail=f"ObjectType '{body.target_object_type_id}' not found")

    cells = db.query(FusCell).filter(FusCell.sheet_id == sheet_id).all()
    raw_by_ref = {c.ref: c.raw for c in cells}
    values = evaluate_cells(raw_by_ref, lookup_source=_make_lookup_source(db))

    staged: List[Dict[str, Any]] = []
    applied = 0
    for mapping in body.row_mappings:
        inst = db.query(models.ObjectInstance).filter(
            models.ObjectInstance.id == mapping.object_id,
            models.ObjectInstance.object_type_id == body.target_object_type_id,
        ).first()
        if not inst:
            staged.append({
                "object_id": mapping.object_id, "found": False,
                "changes": {}, "errors": ["object not found for target type"],
            })
            continue

        props = dict(inst.properties or {})
        changes: Dict[str, Any] = {}
        errors: List[str] = []
        for prop_name, ref in mapping.cells.items():
            nref = normalize_ref(ref)
            if parse_ref(nref) is None:
                errors.append(f"invalid cell ref '{ref}'")
                continue
            new_val = values.get(nref, "")
            if isinstance(new_val, str) and new_val in ERROR_TOKENS:
                errors.append(f"{nref} computed to error {new_val}")
                continue
            changes[prop_name] = {
                "ref": nref, "old": props.get(prop_name), "new": new_val,
            }

        entry = {
            "object_id": mapping.object_id, "found": True,
            "changes": changes, "errors": errors,
        }

        if body.commit and not errors and changes:
            for prop_name, ch in changes.items():
                props[prop_name] = ch["new"]
            inst.properties = props
            inst.updated_at = int(time.time())
            entry["applied"] = True
            applied += 1
        else:
            entry["applied"] = False
        staged.append(entry)

    if body.commit and applied:
        db.add(models_action.AuditLog(
            id=uuid.uuid4().hex, actor="system",
            event_type="fusion.write_back.committed", subject_type="fus_sheet",
            subject_id=sheet_id,
            payload={"target_object_type_id": body.target_object_type_id,
                     "objects_updated": applied}))
        db.commit()
    else:
        db.rollback()

    return {
        "sheet_id": sheet_id,
        "target_object_type_id": body.target_object_type_id,
        "committed": bool(body.commit and applied),
        "objects_staged": len(staged),
        "objects_applied": applied,
        "staged_changes": staged,
    }
