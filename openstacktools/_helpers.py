import sys
from typing import Callable, Any

CONSENT_AGREED = ["y", "yes", "yup", "ok", "okey", "do it", "get on with it"]


def get_consent(outputter: Callable[[str], Any]=print) -> bool:
    """
    Gets consent from the user.
    :param outputter: method that output the given message to the user
    :return: whether the user consents
    """
    outputter("Are you sure you wish to continue (y/n)?")
    consent = sys.stdin.readline().lower().strip()
    return consent in CONSENT_AGREED


def null_op(*args, **kwargs):
    """
    Does absolutely nothing.
    :param args: arguments
    :param kwargs: named arguments
    """
