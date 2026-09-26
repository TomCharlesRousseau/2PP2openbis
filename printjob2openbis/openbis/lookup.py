"""
Read-only lookups in openBIS.
"""

from typing import Iterable, Set

from pybis import Openbis

_BATCH_SIZE = 100


def existing_permids(openbis: Openbis, permids: Iterable[str]) -> Set[str]:
    """
    Return the permIds (of objects / samples) that exist in openBIS.

    Queries in batches; permIds that do not exist are simply absent from the
    server's answer.

    Args:
        openbis: Logged-in pybis session.
        permids: PermIds to look up.

    Returns:
        Subset of *permids* that exist.
    """
    wanted = sorted(set(permids))
    found: Set[str] = set()
    for start in range(0, len(wanted), _BATCH_SIZE):
        batch = wanted[start:start + _BATCH_SIZE]
        response = openbis.get_sample(batch, raw_response=True)
        found.update(sample["permId"]["permId"] for sample in response.values())
    return found


def vocabulary_terms(openbis: Openbis, vocabulary: str) -> Set[str]:
    """
    Return the term codes of a controlled vocabulary (e.g. ``BAM_OE``).

    Args:
        openbis: Logged-in pybis session.
        vocabulary: Vocabulary code.

    Returns:
        Term codes; empty if the vocabulary has no terms.
    """
    terms = openbis.get_terms(vocabulary=vocabulary).df
    return set(terms["code"]) if "code" in terms.columns else set()
