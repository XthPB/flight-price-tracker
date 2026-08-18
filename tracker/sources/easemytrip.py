"""EaseMyTrip source (Indian OTA), regular + student fares.

EMT's search API (flightservice-node.easemytrip.com/AirAvail_Lights/AirBus_New)
requires a per-session search token. The chain, replicated from their web app
(Scripts/ApiCallLight_new.js): call etoken/jypppm with a fixed ATK header to
get {ITK, b}, then exchange them at etoken/tttyyty — with AES-128-CBC
(key = iv = "hylW@zmEQdG@4Idr", the site's `encKeySrch`) encrypting the header
fields — for the STK search token.

EMT prices international itineraries per direction, so one search per
outbound date and one per return date covers the entire date grid; a round
trip is the sum of the two one-way fares (which is what EMT charges in its
own booking flow). The student fare mode is the same search with
airline="Student" — discounts apply only on carriers that offer them, so
student and regular prices often match on the cheapest option.
"""

import base64
import logging
import re
import time
import uuid

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from ..quotes import Quote

log = logging.getLogger(__name__)

SOURCE_ID = "easemytrip"
SOURCE_NAME = "EaseMyTrip"
STUDENT_SOURCE_ID = "easemytrip-student"
STUDENT_SOURCE_NAME = "EaseMyTrip · Student"

AES_KEY = b"hylW@zmEQdG@4Idr"
ATK = "c0ruxuOD/XqyNXB3kRAqvRUliyqhyFOOUwgDTCP1tLx09TRNEbblvRQLgfPz2ivf"
AUTK_PREFIX = "EMT|EMTWvggk6zYLVynBA56C3aNn4HLREMHV9bEP9Q"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

AIRLINE_NAMES = {
    "6E": "IndiGo", "AI": "Air India", "IX": "Air India Express", "UK": "Vistara",
    "EY": "Etihad Airways", "EK": "Emirates", "QR": "Qatar Airways", "GF": "Gulf Air",
    "WY": "Oman Air", "SV": "Saudia", "KU": "Kuwait Airways", "J9": "Jazeera Airways",
    "LH": "Lufthansa", "LX": "Swiss", "KL": "KLM", "AF": "Air France",
    "BA": "British Airways", "VS": "Virgin Atlantic", "TK": "Turkish Airlines",
    "LO": "LOT Polish", "AZ": "ITA Airways", "MS": "EgyptAir", "ET": "Ethiopian Airlines",
    "SU": "Aeroflot", "KC": "Air Astana", "HY": "Uzbekistan Airways", "T5": "Turkmenistan",
}


def _enc(s: str) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY)
    return base64.b64encode(cipher.encrypt(pad(s.encode(), 16))).decode()


def _ddmmyyyy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


class _Client:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Origin": "https://flight.easemytrip.com",
            "Referer": "https://flight.easemytrip.com/",
        })
        self.qname = str(uuid.uuid4())
        self.stk = None

    def refresh_token(self):
        r1 = self.session.post(
            "https://gi.easemytrip.com/etm/api/etoken/jypppm",
            json={}, headers={"ATK": ATK}, timeout=30)
        r1.raise_for_status()
        itk, ip = r1.json()["ITK"], r1.json()["b"]
        r2 = self.session.post(
            "https://gi.easemytrip.com/etm/api/etoken/tttyyty",
            json={"UserName": "EMT", "ITK": _enc(itk), "IP": _enc(ip)},
            headers={
                "autk": _enc(f"{AUTK_PREFIX}|{ip}|{itk}"),
                "itk": _enc(f"{self.qname}|https://flight.easemytrip.com/FlightList/Index"),
            },
            timeout=30)
        r2.raise_for_status()
        self.stk = r2.json()["STK"]

    def search_oneway(self, org: str, dest: str, date_iso: str, fare: str) -> list[dict]:
        """One-way search; fare is "undefined" (regular) or "Student"."""
        if not self.stk:
            self.refresh_token()
        payload = {
            "org": org, "dept": dest, "adt": "1", "chd": "0", "inf": "0",
            "queryname": self.qname, "TraceId": self.qname,
            "deptDT": date_iso, "arrDT": None,
            "userid": "", "IsDoubelSeat": False, "isDomestic": "true", "isOneway": True,
            "airline": fare, "VIP_CODE": "", "VIP_UNIQUE": "", "Cabin": 0,
            "currCode": "INR", "appType": 1, "isSingleView": False, "ResType": 0,
            "IsNBA": True, "CouponCode": "", "IsArmedForce": False, "AgentCode": "",
            "IsWLAPP": False, "IsFareFamily": False, "serviceid": "EMTSERVICE",
            "serviceDepatment": "", "IpAddress": "", "LoginKey": "", "UUID": "", "IsAds": False,
            "TKN": self.stk,
            "requesttime": "2026-01-01T00:00:00.000Z", "tokenResponsetime": "2026-01-01T00:00:00.000Z",
        }
        for attempt in range(3):
            r = self.session.post(
                "https://flightservice-node.easemytrip.com/AirAvail_Lights/AirBus_New",
                json=payload, timeout=90)
            if "TOKEN NOT VALID" in r.text[:40]:
                self.refresh_token()
                payload["TKN"] = self.stk
                continue
            r.raise_for_status()
            data = r.json()
            journeys = data.get("j") or []
            return (journeys[0].get("s") or []) if journeys else []
        raise RuntimeError("easemytrip: token kept getting rejected")


def _parse_option(opt: dict) -> dict | None:
    """Extract price/airline/stops/duration from one search result option."""
    price = opt.get("TF")
    if not price:
        return None
    try:
        leg = opt["l_OB"][0]
        raw = (leg.get("BkKY") or [""])[0].split("`")[0].strip()
        m = re.match(r"^([A-Z0-9]{2})\b", raw)
        code = m.group(1) if m else ""
        stops_txt = (leg.get("STP") or "").strip("|")
        stops = 0 if "Non" in stops_txt else int(stops_txt[0]) if stops_txt[:1].isdigit() else None
        jt = leg.get("JyTm") or ""  # "12h 40m"
        h, m = 0, 0
        for part in jt.split():
            if part.endswith("h"): h = int(part[:-1])
            elif part.endswith("m"): m = int(part[:-1])
        duration = h * 60 + m or None
    except (KeyError, IndexError, ValueError, TypeError):
        code, stops, duration = "", None, None
    return {
        "price": float(price),
        "airline": AIRLINE_NAMES.get(code, code or "?"),
        "stops": stops,
        "duration": duration,
    }


def _best_per_date(client, org, dest, dates, fare, delay) -> dict:
    best = {}
    for date in dates:
        try:
            options = client.search_oneway(org, dest, date, fare)
        except Exception as e:
            log.warning("easemytrip: %s->%s %s (%s) failed: %s", org, dest, date, fare, e)
            continue
        parsed = [p for p in (_parse_option(o) for o in options) if p]
        if parsed:
            best[date] = min(parsed, key=lambda p: p["price"])
        time.sleep(delay)
    return best


def _booking_url(route, out_date, ret_date, student: bool) -> str:
    org, dest = route["origin"], route["destination"]
    org_city, dest_city = route["origin_city"], route["destination_city"]
    org_country = route.get("origin_country", "")
    dest_country = route.get("destination_country", "")
    ar = "Student" if student else "undefined"
    return (
        "https://flight.easemytrip.com/FlightList/Index"
        f"?srch={org}-{org_city}-{org_country}|{dest}-{dest_city}-{dest_country}|{_ddmmyyyy(out_date)}"
        f"&rtn={dest}-{dest_city}-{dest_country}|{org}-{org_city}-{org_country}|{_ddmmyyyy(ret_date)}"
        f"&px=1-0-0&cbn=0&ar={ar}&isow=false&isdm=true&lng=&IsDoubleSeat=false"
        "&CCODE=IN&curr=INR&apptype=B2C"
    )


def fetch(config) -> list[Quote]:
    route = config["route"]
    out_dates = config["dates"]["outbound"]
    ret_dates = config["dates"]["return"]
    delay = config.get("easemytrip", {}).get("request_delay_seconds", 1.0)
    currency = config["currency"]
    if currency != "INR":
        log.warning("easemytrip: only INR supported, skipping")
        return []

    client = _Client()
    quotes = []
    for fare, source_id, source_name in [
        ("undefined", SOURCE_ID, SOURCE_NAME),
        ("Student", STUDENT_SOURCE_ID, STUDENT_SOURCE_NAME),
    ]:
        student = fare == "Student"
        out_best = _best_per_date(client, route["origin"], route["destination"], out_dates, fare, delay)
        ret_best = _best_per_date(client, route["destination"], route["origin"], ret_dates, fare, delay)
        for o_date, o in out_best.items():
            for r_date, r in ret_best.items():
                quotes.append(Quote(
                    source=source_id,
                    source_name=source_name,
                    out_date=o_date,
                    ret_date=r_date,
                    price=o["price"] + r["price"],
                    currency="INR",
                    airlines=sorted({o["airline"], r["airline"]}),
                    stops_out=o["stops"],
                    stops_in=r["stops"],
                    duration_min=(o["duration"] + r["duration"]) if o["duration"] and r["duration"] else None,
                    booking_url=_booking_url(route, o_date, r_date, student),
                    fare_type="student" if student else "regular",
                ))
    return quotes
