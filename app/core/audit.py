import json
import logging
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

audit_logger = logging.getLogger("academic_agent.audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False

if not audit_logger.handlers:
    handler = logging.FileHandler(
        LOG_DIR / "tools.jsonl",
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)


def write_audit(record: dict):
    audit_logger.info(
        json.dumps(record, ensure_ascii=False)
    )