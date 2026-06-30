# REMIT UMM Electricity Schema V3 parser (U1.2 extension).
import xml.etree.ElementTree as ET

_NS = {
    "m": "http://www.acer.europa.eu/REMIT/REMITUMMElectricitySchema_V3.xsd",
    "c": "http://www.acer.europa.eu/REMIT/REMITUMMCommonSchema_V2.xsd",
}
_DISMISSED = {"dismissed", "withdrawn", "cancelled"}


def _txt(node, path):
    el = node.find(path, _NS)
    return el.text.strip() if el is not None and el.text else None


def parse_remit_umm(xml_text: str) -> list[dict]:
    """Parse a REMITUrgentMarketMessages XML doc into one record per UMM.

    Returns dicts with keys: message_id, bidding_zone (EIC), asset, asset_eic,
    fuel, event_type, unavailability_type, status, reason, start, end,
    unavailable_mw, available_mw, installed_mw, participant. Dismissed/withdrawn
    UMMs are skipped (not live)."""
    out: list[dict] = []
    root = ET.fromstring(xml_text)
    for umm in root.findall("m:UMM", _NS):
        status = _txt(umm, "m:event/m:eventStatus")
        if status and status.strip().lower() in _DISMISSED:
            continue
        cap = umm.find("m:capacity", _NS)
        rec = {
            "message_id": _txt(umm, "m:messageId"),
            "bidding_zone": _txt(umm, "m:biddingZone"),
            "asset": _txt(umm, "m:affectedAsset/c:name"),
            "asset_eic": _txt(umm, "m:affectedAsset/c:eic"),
            "fuel": _txt(umm, "m:fuelType"),
            "event_type": _txt(umm, "m:event/m:eventType"),
            "unavailability_type": _txt(umm, "m:unavailabilityType"),
            "status": status,
            "reason": _txt(umm, "m:unavailabilityReason"),
            "start": _txt(umm, "m:event/m:eventStart"),
            "end": _txt(umm, "m:event/m:eventStop"),
            "participant": _txt(umm, "m:marketParticipant/c:name"),
            "installed_mw": _txt(cap, "m:installedCapacity") if cap is not None else None,
            "unavailable_mw": _txt(cap, "m:capacityInterval/m:unavailableCapacity") if cap is not None else None,
            "available_mw": _txt(cap, "m:capacityInterval/m:availableCapacity") if cap is not None else None,
        }
        out.append(rec)
    return out