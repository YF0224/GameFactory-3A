"""Normalize terminal decoration before applying the existing native error policy."""
import re

ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PRODUCT_ERROR = re.compile(r"(?m)^(?:SCRIPT ERROR|ERROR|Parse Error|USER ERROR)\b")


def godot_product_errors(text: str) -> bool:
    return bool(PRODUCT_ERROR.search(ANSI_CSI.sub("", text)))
