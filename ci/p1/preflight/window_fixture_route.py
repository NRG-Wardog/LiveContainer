"""Print a reviewed opt-in routing proposal; never modify the candidate source."""
from pathlib import Path
import difflib
import hashlib

BASE = Path(__file__).resolve().with_name('app.swift')
BASE_SHA256 = '788a48372192d60c908f386ee18c69758e379e2973ef94cd69a2f35bbb65d711'
OLD_INIT = '    init() { UIPasteboard.general.string = "" }'
NEW_INIT = '''    init() {
        if !P1WindowCaptureConfiguration.isRequested(ProcessInfo.processInfo.arguments) {
            UIPasteboard.general.string = ""
        }
    }'''
OLD_ROUTE = '                if ProcessInfo.processInfo.arguments.contains("--recovery") { P1ProbeRecoveryScreen() }'
NEW_ROUTE = '''                if P1WindowCaptureConfiguration.isRequested(ProcessInfo.processInfo.arguments) {
                    P1WindowCaptureFixtureScreen()
                }
                else if ProcessInfo.processInfo.arguments.contains("--recovery") { P1ProbeRecoveryScreen() }'''


def proposed_source(source):
    if hashlib.sha256(source.encode()).hexdigest() != BASE_SHA256:
        raise ValueError('preflight app source drift')
    if source.count(OLD_INIT) != 1 or source.count(OLD_ROUTE) != 1:
        raise ValueError('routing anchors ambiguous')
    return source.replace(OLD_INIT, NEW_INIT).replace(OLD_ROUTE, NEW_ROUTE)


if __name__ == '__main__':
    source = BASE.read_text()
    print(''.join(difflib.unified_diff(source.splitlines(True), proposed_source(source).splitlines(True),
        fromfile='a/ci/p1/preflight/app.swift', tofile='b/ci/p1/preflight/app.swift')), end='')
