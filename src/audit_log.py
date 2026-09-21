"""Deprecated shim for the canonical audit-chain implementation.

The chain rule — :data:`CHAIN_FIELDS`, field coercion, signature
computation, verification, and chain ordering — now lives in exactly one
place: :mod:`ai_billing_audit.audit_chain`.

This module used to hold its own copy. That copy is what made the chain
unable to verify its own output (issue #113): the writer hashed
``data_elements`` as canonical JSON while this verifier hashed ``str()``
of the parsed dict, so every row produced by the append path was reported
as tampered from index 0. The QA harness missed it because ``psql -A``
happens to return the column as text, which is the one case where the two
rules agreed.

Everything here is a re-export so existing imports keep working —
``tests/test_audit_log.py`` and the ``scripts/qa_audit_chain_*.py``
harnesses import from this path. New code should import from
``ai_billing_audit.audit_chain`` directly.

``walk_chain`` is defined here as well as in ``audit_chain`` for historical
reasons: it was part of this module's public surface and the runbook calls
it by this path.
"""

from __future__ import annotations

from ai_billing_audit.audit_chain import (
    CHAIN_FIELDS,
    GENESIS_PREVIOUS_SIGNATURE,
    coerce_field,
    compute_signature,
    verify_chain,
    walk_chain,
)

__all__ = [
    "CHAIN_FIELDS",
    "GENESIS_PREVIOUS_SIGNATURE",
    "coerce_field",
    "compute_signature",
    "verify_chain",
    "walk_chain",
]
