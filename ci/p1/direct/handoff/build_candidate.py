"""Generate only this directory's isolated XCTest candidate; never edit inputs."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "window-capture-candidate" / "ci" / "p1"
ORIGINAL_SHA = "9105711cd1b10860549025109bdc2087976d6661201ab44307e08473b7a7a783"
PREFLIGHT_SHA = "0e6504ffd4b964822f2b87a4cb5be89e99e1565882d5935a8dd18ae078efd131"
PRIMITIVES_SHA = "c8f21f91675173c959f73c92bbc49a2466d66c133def65779c79501ebee182c2"
IMPORTS = "import CoreFoundation\nimport CryptoKit\nimport Darwin\n"
PRIMITIVES_BEGIN = "// P1_DIRECT_REUSED_PRIMITIVES_BEGIN\n"
PRIMITIVES_END = "// P1_DIRECT_REUSED_PRIMITIVES_END\n"
OBSERVER_BEGIN = "// P1_DIRECT_OBSERVER_BEGIN\n"
OBSERVER_END = "// P1_DIRECT_OBSERVER_END\n"
START = '        let directMethodStarted = ProcessInfo.processInfo.systemUptime\n        guard let directSession = P1DirectHandoff.sessionOrFail() else { return }\n'
LAUNCH = 'let app = XCUIApplication(); app.launchArguments = ["--scenario", scenario]; app.launch()'
DIRECT_LAUNCH = 'let app = XCUIApplication(); app.launchArguments = ["--scenario", scenario, "--session", directSession]; app.launch()'
HOOK = '''        guard P1DirectHandoff.beforeBaseline(test: self, app: app, scenario: scenario,
            session: directSession, methodStarted: directMethodStarted,
            copy: copy, marker: marker, baselineReady: baselineReady) else { return }
'''
BASELINE = '        let baselineBefore = ProcessInfo.processInfo.systemUptime; baselineReady.tap()\n'


def digest(data):
    return sha256(data).hexdigest()


def source_bytes():
    original = (SOURCE / "video/ui_tests.swift").read_bytes()
    preflight = (SOURCE / "preflight/runner_ui_tests.swift").read_bytes()
    if digest(original) != ORIGINAL_SHA or digest(preflight) != PREFLIGHT_SHA:
        raise ValueError("sealed original source changed; re-review required")
    source = preflight.decode()
    primitives = source[source.index("private struct P1CapabilityError:"):
                        source.index("private struct P1CapabilityCommand:")]
    if digest(primitives.encode()) != PRIMITIVES_SHA:
        raise ValueError("reviewed primitive block changed")
    return original.decode(), primitives


def generate():
    original, primitives = source_bytes()
    observer = (HERE / "observer.swift").read_text()
    candidate = original.replace("import Foundation\n", "import Foundation\n" + IMPORTS, 1)
    candidate = candidate.replace("final class P0SignInUITests", PRIMITIVES_BEGIN + primitives +
                                  PRIMITIVES_END + "\n" + OBSERVER_BEGIN + observer +
                                  OBSERVER_END + "\nfinal class P0SignInUITests", 1)
    if candidate.count(LAUNCH) != 1 or candidate.count(BASELINE) != 1:
        raise ValueError("ambiguous instrumentation location")
    orientation = '        continueAfterFailure = false; XCUIDevice.shared.orientation = .portrait\n'
    if candidate.count(orientation) != 1:
        raise ValueError("ambiguous method start")
    candidate = candidate.replace(orientation, START + orientation, 1)
    candidate = candidate.replace("        " + LAUNCH, "        " + DIRECT_LAUNCH, 1)
    candidate = candidate.replace(BASELINE, HOOK + BASELINE, 1)
    (HERE / "ui_tests.swift").write_text(candidate)
    manifest = dict(schema="p1-direct-observer-source-binding-v1",
                    originalSource="../../window-capture-candidate/ci/p1/video/ui_tests.swift",
                    originalSourceSHA256=ORIGINAL_SHA,
                    primitivesSource="../../window-capture-candidate/ci/p1/preflight/runner_ui_tests.swift",
                    primitivesSourceSHA256=PREFLIGHT_SHA, primitivesBlockSHA256=PRIMITIVES_SHA,
                    observerSHA256=digest(observer.encode()), candidateSHA256=digest(candidate.encode()),
                    sourceDelta="environment guard, session launch argument, and one pre-baseline handoff guard",
                    nativeCompiled=False, nativeExecuted=False, admissionEligible=False)
    (HERE / "source-binding.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True, indent=2))
