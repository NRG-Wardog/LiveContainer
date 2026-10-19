"""Generate an opt-in fixture delta; never edit maintained production sources."""
from pathlib import Path
import hashlib

APP_SHA='3fa3f4329dd0dac18a94d8c43922e545be87ebed5136b7a49d18b02ca57118ff'
PACKET_SOURCE_SHA='8b6493a7015ff5c4dbf33a81ba37f27972ba1069653bfca31d9ecf6c0b4da0ee'
METHOD_ANCHOR='    func markerGeometry(_ rect: CGRect) {'
METHOD='''    private let directAnchorReceipts = P1DirectAnchorReceiptBuffer()
    func directAnchorDraw(_ row: [String: Any]) { directAnchorReceipts.append(row) }
'''
START_ANCHOR='            journal.start()\n'
START_HOOK='            directAnchorReceipts.attach(journal.append)\n'
OVERLAY_ANCHOR='        }.navigationViewStyle(.stack)\n'
OVERLAY='        .overlay(P1DirectRegistrationOverlay(receipt: probe.directAnchorDraw))\n'


def sha(text):return hashlib.sha256(text.encode()).hexdigest()


def packet_enum(source):
    if sha(source)!=PACKET_SOURCE_SHA:raise ValueError('reviewed packet source drift')
    start=source.index('enum P1WindowCapturePacket {')
    end=source.index('\nprivate enum P1WindowCaptureReady',start)
    return source[start:end]


def render(app_source,packet_source,overlay_source):
    if sha(app_source)!=APP_SHA:raise ValueError('maintained feedback fixture drift')
    if any(app_source.count(anchor)!=1 for anchor in (METHOD_ANCHOR,OVERLAY_ANCHOR,START_ANCHOR)):
        raise ValueError('ambiguous fixture routing anchors')
    generated=(app_source.replace(METHOD_ANCHOR,METHOD+METHOD_ANCHOR)
               .replace(OVERLAY_ANCHOR,OVERLAY_ANCHOR+OVERLAY)
               .replace(START_ANCHOR,START_HOOK+START_ANCHOR))
    return generated+'\n'+packet_enum(packet_source)+'\n'+overlay_source
