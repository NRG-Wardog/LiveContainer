# Isolated direct-feedback implementation

These local modules are validation primitives for the reviewed direct host-window evidence design. They are not integrated into the published candidate or any workflow. No result from them establishes feedback acceptance without native source/ownership/pixel/receipt/cleanup evidence.

- `clock/direct_clock.py`: exact rational mach conversion, all 24 ordered phase samples, phase/common intersections, combined app/presentation uncertainty gate, outward integer serialization and an in-process Darwin sampler binding.
- `clock/direct_coverage.py`: complete point-observation inventory and conservative protocol boundary/gap coverage. No assumed frame persistence; idle records supply no pixels. Pixel, session, geometry and label verification are mandatory separate stages.
- `protocol/transitions.py`: conservative actual receipt ordering/context validation for the original timeout/replacement/dismissal scenarios. Input receipt intervals require a reviewed native adapter; synthetic tests do not establish actual timing.
- `geometry/`: independent retained-anchor, frozen ROI and inclusive budget validation primitives under implementation.

Focused clock/coverage checks:

    python3 -m unittest discover -s p1-stall-isolation/direct-feedback-local/clock -v
    python3 -O -m unittest discover -s p1-stall-isolation/direct-feedback-local/clock -v

Native mach sampling has not been executed in this Linux workspace. The exact native helper, source identity, channel integration, registration anchors, complete sample inventory, one-case capture scheduling and resource limits still require implementation and independent review. Production declarations, timer, original XCTest methods and published source remain unchanged.
