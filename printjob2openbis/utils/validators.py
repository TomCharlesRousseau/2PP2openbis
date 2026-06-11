"""
Input validation helpers for printjob2openbis.
"""

from typing import Any

# Values that pandas uses for missing / empty cells.
_EMPTY_SENTINELS = {"nan", "none", "n/a", ""}


def is_empty(value: Any) -> bool:
    """
    Return True if *value* represents an empty / missing cell.

    Handles ``None``, ``float('nan')``, and common string representations
    of missing data.

    Args:
        value: Cell value to test.

    Returns:
        ``True`` if the value should be treated as empty.
    """
    if value is None:
        return True
    try:
        import math
        if math.isnan(float(value)):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _EMPTY_SENTINELS


def is_valid_code(code: Any) -> bool:
    """
    Return True if *code* is a non-empty string suitable as an openBIS code.

    Args:
        code: Value to validate.

    Returns:
        ``True`` if the code is usable.
    """
    return not is_empty(code)


def is_valid_perm_id(perm_id: Any) -> bool:
    """
    Return True if *perm_id* looks like a non-empty openBIS permId.

    A permId is typically a numeric timestamp string such as
    ``20210101000000000-12345``. This function only checks that the value
    is a non-empty string; it does not verify the exact format so that
    the validator stays forward-compatible.

    Args:
        perm_id: Value to validate.

    Returns:
        ``True`` if the permId is non-empty.
    """
    return not is_empty(perm_id)
