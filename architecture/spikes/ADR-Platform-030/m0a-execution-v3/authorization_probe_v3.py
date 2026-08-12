#!/usr/bin/env python3
"""Build unambiguous kubectl SubjectAccessReview commands for M0a v3."""

from __future__ import annotations


def can_i_args(
    verb: str,
    resource: str,
    *,
    name: str | None = None,
    namespace: str | None = None,
    subresource: str | None = None,
) -> list[str]:
    if name and subresource:
        raise ValueError("name and subresource must not be combined in this boundary")
    target = f"{resource}/{name}" if name else resource
    args = ["auth", "can-i", verb, target]
    if subresource:
        args.extend(["--subresource", subresource])
    if namespace:
        args.extend(["--namespace", namespace])
    return args


def token_request_denial_args() -> list[str]:
    return can_i_args(
        "create",
        "serviceaccounts",
        subresource="token",
        namespace="openkubes-system",
    )
