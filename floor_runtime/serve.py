"""MCP server over stdio for admitted symbolic tools.

    python3 -m floor_runtime --data ./exports --tools ./floor --list
    python3 -m floor_runtime --data ./exports --tools ./floor --check
    python3 -m floor_runtime --data ./exports --tools ./floor          (serve)

Every tool it serves was admitted by the Perslis gate and carries an Ed25519
signature. An unsigned or edited spec is refused and its tool is simply not
offered — the server starts, says which specs it refused, and serves the rest.

The data is re-read whenever it changes on disk. If a changed file cannot be
read, calls are refused until it can — stale data is never served silently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from . import __version__
from .data import DataSource, LoadError
from .journal import Journal
from .explain import explain
from .pipeline import DataError, PipelineError, describe, run, to_plain, validate
from .signing import SignatureError, require

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
GAP_TOOL = "report_gap"
PUBLIC_REASON = "_public_reason"   # log-safe reason; never sent to the client


def tool_name(question_class: str) -> str:
    """MCP tool names: [A-Za-z0-9_-]{1,64}."""
    name = "derive_" + re.sub(r"[^A-Za-z0-9_-]", "_", question_class)
    if len(name) > 64:
        name = name[:55] + "_" + hashlib.sha256(name.encode()).hexdigest()[:8]
    return name


class Tool:
    def __init__(self, envelope: dict):
        spec = envelope["spec"]
        self.question_class = spec["question_class"]
        self.pipeline = spec["pipeline"]
        self.table = envelope["table"]
        self.question = spec.get("question") or ""
        self.do_not = spec.get("do_not") or []
        self.issued_to = envelope.get("issued_to")
        validate(self.pipeline)
        self.human = describe(self.pipeline)
        self.readback = explain(self.pipeline, self.table)
        self.review = envelope.get("review") or {}
        self.name = tool_name(self.question_class)

    def __call__(self, ctx: dict) -> dict:
        base = {"tool": self.name, "table": self.table}
        try:
            value, found = run(ctx, self.table, self.pipeline)
        except DataError as exc:
            return {"status": "REFUSED", **base,
                    "reason": f"the data cannot support a checked answer: {exc}",
                    PUBLIC_REASON: f"the data cannot support a checked answer: {exc.public}"}
        if not found:
            return {"status": "NO_EVIDENCE", **base,
                    "reason": "a table this tool reads is not in the supplied data"}
        if value is None or value == {} or value == []:
            return {"status": "NO_VALUE", **base,
                    "reason": "no rows matched, so there is no value to report"}
        return {"status": "DERIVED", **base, "question_class": self.question_class,
                "value": to_plain(value), "model_calls": 0, "derivation": self.human}

    def spec(self) -> dict:
        what = f"Question it was built for: {self.question}. " if self.question else ""
        return {"name": self.name,
                "description": (f"{what}What it computes, exactly: {self.readback} "
                                f"Runs locally over the '{self.table}' data; no model in "
                                f"the loop. Takes no arguments. If this procedure is not "
                                f"exactly what the user asked, do not use it — call "
                                f"report_gap instead."),
                "inputSchema": {"type": "object", "properties": {}}}


GAP_SPEC = {
    "name": GAP_TOOL,
    "description": ("Call this when the user asks a question about their data that "
                    "none of the other tools answers exactly. It records the question "
                    "in a local file so a tool can be built for it. Nothing leaves "
                    "this machine. Do not use it for questions a tool already answers."),
    "inputSchema": {"type": "object",
                    "properties": {"question": {"type": "string",
                                                "description": "the user's question, verbatim"},
                                   "note": {"type": "string",
                                            "description": "optional: why no tool fits"}},
                    "required": ["question"]}}


def load_tools(tools_dir, trusted: dict | None = None) -> tuple[list, list]:
    """(tools, refusals). A spec loads whole or not at all."""
    d = Path(tools_dir) / "specs"
    tools, refused, seen = [], [], set()
    if not d.is_dir():
        return tools, [f"no specs directory at {d}"]
    for path in sorted(d.glob("*.json")):
        try:
            tool = Tool(require(json.loads(path.read_text()), trusted))
            if tool.name in seen:
                raise PipelineError(f"duplicate tool name {tool.name}")
            seen.add(tool.name)
            tools.append(tool)
        except (ValueError, KeyError, TypeError, SignatureError, PipelineError) as exc:
            refused.append(f"{path.name}: {type(exc).__name__}: {exc}")
    return tools, refused


def _text(obj) -> list:
    return [{"type": "text", "text": json.dumps(obj, default=str)}]


class Server:
    def __init__(self, source, tools: list, journal: Journal | None = None):
        self.source, self.tools = source, {t.name: t for t in tools}
        self.journal = journal or Journal(None)
        self._answers: dict = {}      # tool name -> (data version, answer)

    def handle(self, msg: dict):
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if mid is None:                       # notifications get no reply
            return None
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[-1],
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "perslis-symbolic-floor",
                                         "version": __version__}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t.spec() for t in self.tools.values()] + [GAP_SPEC]}
            elif method == "tools/call":
                result = self._call(params)
            else:
                return {"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32601, "message": f"no method {method}"}}
        except Exception as exc:              # fail closed, never crash the loop
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _call(self, params: dict) -> dict:
        name, args = params.get("name"), params.get("arguments") or {}
        if name == GAP_TOOL:
            q = args.get("question")
            if not isinstance(q, str) or not q.strip():
                return {"isError": True, "content": _text({"error": "question is required"})}
            note = args.get("note")
            self.journal.gap(q, note if isinstance(note, str) else None)
            return {"isError": False, "content": _text(
                {"status": "RECORDED", "note": "saved on this machine only; no tool "
                                               "answers this yet"})}
        tool = self.tools.get(name)
        if tool is None:
            return {"isError": True, "content": _text({"error": f"no tool '{name}'"})}
        started = time.perf_counter()
        try:
            ctx = self.source.get()
            cached = self._answers.get(tool.name)
            if cached is not None and cached[0] == self.source.version:
                out = dict(cached[1])             # same data, same answer: deterministic
            else:
                out = tool(ctx)
                self._answers[tool.name] = (self.source.version, dict(out))
        except LoadError as exc:
            out = {"status": "REFUSED", "tool": tool.name,
                   "reason": f"the data changed on disk and could not be re-read: {exc}"}
        public = out.pop(PUBLIC_REASON, out.get("reason"))
        self.journal.call(tool.name, out["status"], (time.perf_counter() - started) * 1000,
                          out.get("value"), out.get("reason") if self.journal.log_values
                          else public)
        return {"isError": out["status"] != "DERIVED", "content": _text(out)}

    def serve(self, stdin=None, stdout=None) -> None:
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                reply = {"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700, "message": "parse error"}}
            else:
                reply = self.handle(msg) if isinstance(msg, dict) else None
            if reply is not None:
                stdout.write(json.dumps(reply, default=str) + "\n")
                stdout.flush()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="floor_runtime",
                                 description="Serve admitted symbolic tools over MCP (stdio).")
    ap.add_argument("--data", required=True,
                    help="a .csv/.tsv/.json/.jsonl/.sqlite file, or a directory of them")
    ap.add_argument("--tools", required=True, help="directory holding specs/")
    ap.add_argument("--table", help="table name for a single CSV/JSONL file (default: file name)")
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument("--log-dir", help="where calls.jsonl/gaps.jsonl go (default: <tools>/logs)")
    ap.add_argument("--no-log", action="store_true", help="write no local logs")
    ap.add_argument("--log-values", action="store_true", help="also log answer values")
    ap.add_argument("--share-questions", action="store_true",
                    help="write unanswered questions' TEXT to the shareable log "
                         "(default: text stays in <tools>/private)")
    ap.add_argument("--list", action="store_true", help="print the tools and exit")
    ap.add_argument("--check", action="store_true",
                    help="run every tool once against the data and exit")
    args = ap.parse_args(argv)

    # Trust comes only from keys.py — there is deliberately no flag to add a key.
    tools, refused = load_tools(args.tools)
    for r in refused:
        print(f"refused: {r}", file=sys.stderr)

    if args.list:
        if not tools:
            print("no admitted tools found")
            return 1
        for t in tools:
            who = t.review.get("by", "-")
            print(f"{t.name}\n    question   : {t.question or '-'}\n"
                  f"    computes   : {t.readback}\n    reviewed by: {who}")
        return 0

    try:
        kw = {"max_rows": args.max_rows} if args.max_rows else {}
        source = DataSource(args.data, args.table, **kw)
    except LoadError as exc:
        print(f"cannot read data: {exc}", file=sys.stderr)
        return 2

    if args.check:
        ok = bool(tools)
        for t in tools:
            out = t(source.get())
            out.pop(PUBLIC_REASON, None)
            ok &= out["status"] == "DERIVED"
            shown = out.get("value", out.get("reason"))
            print(f"{out['status']:<11} {t.name}  ->  {json.dumps(shown, default=str)[:200]}")
        if not tools:
            print("no admitted tools found")
        return 0 if ok else 1

    log_dir = None if args.no_log else (args.log_dir or Path(args.tools) / "logs")
    private_dir = None if args.no_log else Path(args.tools) / "private"
    Server(source, tools, Journal(log_dir, args.log_values, private_dir,
                                  args.share_questions)).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
