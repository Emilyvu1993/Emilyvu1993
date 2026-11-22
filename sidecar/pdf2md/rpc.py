"""JSON-lines RPC over stdio. One request per line, one response per line.

Request : {"id": <any>, "method": str, "params": {...}}
Response: {"id": <same>, "result": {...}} | {"id": <same>, "error": {"code","message","detail?"}}
stdout is reserved for protocol; diagnostics go to stderr.
"""
from __future__ import annotations

import json
import sys
import traceback

from . import __version__, engine
from .errors import INTERNAL, RPC_BAD_REQUEST, ConvertError

METHODS = {
    "ping": lambda p: {"pong": True, "version": __version__},
    "inspect": lambda p: engine.inspect(p["pdf_path"], p.get("max_pages", 5), p.get("sample_rows", 3)),
    "match_pattern": lambda p: engine.match_pattern(p["pdf_path"], p["pattern"], p.get("pages"), p.get("limit", 20)),
    "validate_config": lambda p: engine.validate_config(p["config"]),
    "convert": lambda p: engine.convert(p["pdf_path"], p["config"], p["out_tmp_path"], p.get("preview_n", 3)),
}


def handle(line: str) -> dict:
    rid = None
    try:
        req = json.loads(line)
        rid = req.get("id")
        method = req.get("method")
        if method not in METHODS:
            raise ConvertError(RPC_BAD_REQUEST, f"Unknown method '{method}'")
        params = req.get("params") or {}
        try:
            return {"id": rid, "result": METHODS[method](params)}
        except KeyError as e:
            raise ConvertError(RPC_BAD_REQUEST, f"Missing param {e}") from e
    except ConvertError as e:
        return {"id": rid, "error": e.to_dict()}
    except json.JSONDecodeError as e:
        return {"id": rid, "error": {"code": RPC_BAD_REQUEST, "message": f"Invalid JSON: {e}"}}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return {"id": rid, "error": {"code": INTERNAL, "message": f"{type(e).__name__}: {e}"}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        sys.stdout.write(json.dumps(handle(line), ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
