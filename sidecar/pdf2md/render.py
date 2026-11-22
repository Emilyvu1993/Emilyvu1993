"""Jinja2 rendering in a sandbox. StrictUndefined: unknown variable = error, not blank."""
from __future__ import annotations

from typing import Any

from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from .errors import TEMPLATE_RENDER, TEMPLATE_SYNTAX, ConvertError


def md_escape(v: Any) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
    env.filters["md"] = md_escape
    return env


def compile_templates(tpl: dict):
    env = _env()
    compiled = {}
    for part in ("header", "record", "footer"):
        src = tpl.get(part)
        if not src:
            compiled[part] = None
            continue
        try:
            compiled[part] = env.from_string(src)
        except TemplateSyntaxError as e:
            raise ConvertError(
                TEMPLATE_SYNTAX,
                f"Template '{part}' syntax error at line {e.lineno}: {e.message}",
                {"part": part, "line": e.lineno},
            ) from e
    return compiled


def _safe(t, part: str, ctx: dict, record_index: int | None = None) -> str:
    try:
        return t.render(**ctx)
    except UndefinedError as e:
        raise ConvertError(
            TEMPLATE_RENDER,
            f"Template '{part}': {e.message}" + (f" (record {record_index + 1})" if record_index is not None else ""),
            {"part": part, "record_index": record_index, "available_fields": sorted(ctx.get("record", {}).keys())},
        ) from e
    except Exception as e:  # noqa: BLE001
        raise ConvertError(
            TEMPLATE_RENDER, f"Template '{part}' failed: {e}", {"part": part, "record_index": record_index}
        ) from e


def render_record(compiled, rec: dict, index: int) -> str:
    ctx = dict(rec)
    ctx["record"] = rec
    ctx["index"] = index + 1
    return _safe(compiled["record"], "record", ctx, index)


def render_frame(compiled, part: str, records: list[dict], meta: dict) -> str:
    t = compiled[part]
    if t is None:
        return ""
    return _safe(t, part, {"records": records, "count": len(records), **meta})
