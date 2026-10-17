"""Exact local extraction of the independently reviewed layout candidate."""
import hashlib
import re

SOURCE_SHA256 = 'cee763b4190e50f324c666b99e5b117d6468f83de7b8026514968d09aec0e70c'
DECLARATIONS = ('struct V3HostDirectRecoveryRecord', 'enum V3DirectRecoveryPostcondition',
    'enum V3DirectRecoveryHostPolicy', 'enum V3DirectRecoveryPresentationPolicy',
    'private struct V3RecoveryBannerHeightKey', 'private struct V3RecoveryBannerLayout')
START = '        .modifier(V3RecoveryBannerLayout(isPresented:\n'
END = '        .fullScreenCover(item: $status.presentation, onDismiss: {'


def declaration(source, signature):
    matches = list(re.finditer(r'^' + re.escape(signature) + r'(?=\s|:|\{|<)', source, re.M))
    if len(matches) != 1: raise ValueError('ambiguous declaration ' + signature)
    close = re.search(r'^}[ \t]*$', source[matches[0].end():], re.M)
    if close is None: raise ValueError('unclosed declaration')
    return source[matches[0].start():matches[0].end() + close.end()] + '\n'


def fragments(source):
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA256: raise ValueError('layout source drift')
    tabs = declaration(source, 'struct V3UnifiedTabs')
    if tabs.count(START) != 1 or tabs.count(END) != 1: raise ValueError('layout wrapper anchors ambiguous')
    start, end = tabs.index(START), tabs.index(END)
    wrapper = tabs[start:end]
    if end <= start or not wrapper.endswith('        })\n'): raise ValueError('incomplete layout wrapper')
    return {**{s.split()[-1]: declaration(source, s) for s in DECLARATIONS}, 'recovery-modifier': wrapper}


def render(source, template):
    rows = fragments(source)
    for token in ['__P1_RECOVERY_DECLARATIONS__', '__P1_RECOVERY_MODIFIER__']:
        if template.count(token) != 1: raise ValueError('ambiguous template marker')
    return template.replace('__P1_RECOVERY_DECLARATIONS__', '\n'.join(rows[s.split()[-1]] for s in DECLARATIONS)).replace('__P1_RECOVERY_MODIFIER__', rows['recovery-modifier'].rstrip('\n'))
