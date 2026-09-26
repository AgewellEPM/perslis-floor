"""Local, append-only logs. Nothing here touches the network.

Two folders, so "send us your logs" can never include what you did not choose:

    <tools>/logs/        SHAREABLE — safe to send back to Perslis
      calls.jsonl        one line per tool call: time, tool, status, milliseconds,
                         and a refusal reason with the offending VALUES removed.
                         Answer values only with --log-values.
      gaps.jsonl         one line per question no tool answered: a fingerprint
                         and its length — NOT the text — unless --share-questions.

    <tools>/private/     YOURS — never asked for
      gaps.jsonl         the actual text of those questions, so you can read them
                         and pass on the ones you are comfortable sharing.

A log that cannot be written never blocks an answer; it says so on stderr once.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

MAX_QUESTION = 2000
MAX_NOTE = 500


class Journal:
    def __init__(self, directory, log_values: bool = False, private_dir=None,
                 share_questions: bool = False):
        self.dir = Path(directory) if directory else None
        self.private = Path(private_dir) if private_dir else None
        self.log_values = log_values
        self.share_questions = share_questions
        self._warned = False

    def _append(self, directory, name: str, record: dict) -> None:
        if directory is None:
            return
        record = {"at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                  **record}
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / name).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            if not self._warned:
                print(f"journal: cannot write {directory / name}: {exc}", file=sys.stderr)
                self._warned = True

    def call(self, tool: str, status: str, ms: float, value=None, reason=None) -> None:
        rec = {"tool": tool, "status": status, "ms": round(ms, 2)}
        if reason:
            rec["reason"] = reason
        if self.log_values and value is not None:
            rec["value"] = value
        self._append(self.dir, "calls.jsonl", rec)

    def gap(self, question: str, note=None) -> None:
        question = question.strip()[:MAX_QUESTION]
        note = note.strip()[:MAX_NOTE] if isinstance(note, str) and note.strip() else None
        if self.share_questions:
            rec = {"question": question}
            if note:
                rec["note"] = note
            self._append(self.dir, "gaps.jsonl", rec)
            return
        fingerprint = hashlib.sha256(question.lower().encode("utf-8")).hexdigest()[:16]
        self._append(self.dir, "gaps.jsonl",
                     {"question_sha256_16": fingerprint, "chars": len(question),
                      "text": "kept private (see tools/private/gaps.jsonl)"})
        private = {"question": question}
        if note:
            private["note"] = note
        self._append(self.private, "gaps.jsonl", private)
