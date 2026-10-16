"""Exact P1 recovery modifier extraction for a synthetic navigation fixture.

This does not compile V3UnifiedTabs or exercise production recovery services.
The complete input source is pinned, and extracted declarations/modifier are
inserted verbatim. The surrounding navigation and status state are fixtures.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

SOURCE_SHA256 = '3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be'
DECLARATIONS = (
    'struct V3HostDirectRecoveryRecord',
    'enum V3DirectRecoveryPostcondition',
    'enum V3DirectRecoveryHostPolicy',
    'enum V3DirectRecoveryPresentationPolicy',
)
MODIFIER_START = '        .safeAreaInset(edge: .top, spacing: 0) {\n'
MODIFIER_END = '        .fullScreenCover(item: $status.presentation, onDismiss: {'


def _declaration(source: str, signature: str) -> str:
    starts = list(re.finditer(r'^' + re.escape(signature) + r'(?:\s|:|\{)', source, re.M))
    if len(starts) != 1:
        raise ValueError('Expected one production declaration: ' + signature)
    closing = re.search(r'^}[ \t]*$', source[starts[0].end():], re.M)
    if closing is None:
        raise ValueError('Unclosed production declaration: ' + signature)
    end = starts[0].end() + closing.end()
    return source[starts[0].start():end] + '\n'


def recovery_fragments(source_text: str) -> dict[str, str]:
    """Return exact snippets, failing closed on any frozen source byte drift."""
    if hashlib.sha256(source_text.encode('utf-8')).hexdigest() != SOURCE_SHA256:
        raise ValueError('Recovery fixture requires the exact frozen P1 shell source')
    tabs = _declaration(source_text, 'struct V3UnifiedTabs')
    if tabs.count(MODIFIER_START) != 1 or tabs.count(MODIFIER_END) != 1:
        raise ValueError('Recovery modifier anchors are ambiguous or absent')
    start, end = tabs.index(MODIFIER_START), tabs.index(MODIFIER_END)
    modifier = tabs[start:end]
    if end <= start or not modifier.endswith('        }\n'):
        raise ValueError('Recovery modifier is incomplete')
    return {**{signature.split()[-1]: _declaration(source_text, signature)
               for signature in DECLARATIONS}, 'recovery-modifier': modifier}


def generate_recovery_source(source_text: str) -> str:
    """Generate a standalone source file for the existing P1 fixture app target.

    The target must also supply its already-extracted V3DiagnosticBuild enum.
    The caller owns launch routing and Dynamic Type, and must not constrain
    recovery to the separate credentials fixture's 320-point viewport.
    """
    snippets = recovery_fragments(source_text)
    template = Path(__file__).with_name('recovery_app.swift').read_text()
    for token in ('__P1_RECOVERY_DECLARATIONS__', '__P1_RECOVERY_MODIFIER__'):
        if template.count(token) != 1:
            raise ValueError('Recovery template marker is absent or ambiguous: ' + token)
    return template.replace('__P1_RECOVERY_DECLARATIONS__', '\n'.join(
        snippets[signature.split()[-1]] for signature in DECLARATIONS)).replace(
        '__P1_RECOVERY_MODIFIER__', snippets['recovery-modifier'].rstrip('\n'))
