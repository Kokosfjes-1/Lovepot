"""Tar imot en søknad om kjærlighet og lagrer den som en rad i Azure Table Storage."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableClient

# Det søkeren kan søke om, og kvalifikasjonene de kan krysse av for.
# Må stemme med value-attributtene i index.html.
SOKNADSTYPER = {"kjaereste", "date", "kaffe", "klem"}
KVALIFIKASJONER = {"mat", "vitser", "klemmer", "lytter", "dyr", "oppvask"}

_table = None


def get_table() -> TableClient:
    """Lager tabellklienten én gang og gjenbruker den mellom forespørsler."""
    global _table
    if _table is None:
        _table = TableClient.from_connection_string(
            os.environ["STORAGE_CONNECTION_STRING"],
            table_name=os.environ.get("SOKNAD_TABLE", "Soknader"),
        )
    return _table


def respond(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
    )


def text(data: dict, key: str, max_len: int) -> str:
    return str(data.get(key) or "").strip()[:max_len]


def whole_number(value):
    """Gir et heltall, eller None hvis verdien ikke er et helt tall (1.5, "1,5", True osv.)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return respond(400, {"error": "Søknaden ble sendt i feil format. Last inn siden på nytt og prøv igjen."})

    # Honningkrukke: mennesker ser aldri dette feltet, spam-roboter fyller det ut.
    if data.get("website"):
        return respond(200, {"ok": True})

    name = text(data, "name", 100)
    contact = text(data, "contact", 200)
    kind = text(data, "kind", 20)
    reason = text(data, "reason", 1500)
    pickup = text(data, "pickup", 300)
    romance = whole_number(data.get("romance"))
    quals = data.get("qualifications") or []

    if not name:
        return respond(400, {"error": "Skriv inn navnet ditt."})
    if not contact:
        return respond(400, {"error": "Skriv hvordan vi kan nå deg, for eksempel e-post, telefon eller Snapchat."})
    if kind not in SOKNADSTYPER:
        return respond(400, {"error": "Velg hva du søker om."})
    if not reason:
        return respond(400, {"error": "Skriv hvorfor du er den rette."})
    if romance is None or not 1 <= romance <= 10:
        return respond(400, {"error": "Romantikknivået må være et helt tall mellom 1 og 10."})
    if not isinstance(quals, list) or any(q not in KVALIFIKASJONER for q in quals):
        return respond(400, {"error": "En av kvalifikasjonene er ugyldig. Last inn siden på nytt og prøv igjen."})
    if data.get("consent") is not True:
        return respond(400, {"error": "Kryss av for at søknaden er ærlig ment."})

    entity = {
        "PartitionKey": "soknad",
        "RowKey": uuid.uuid4().hex,
        "Name": name,
        "Contact": contact,
        "Kind": kind,
        "Reason": reason,
        "Romance": romance,
        "Qualifications": ",".join(sorted(set(quals))),
        "Pickup": pickup,
        "SubmittedAt": datetime.now(timezone.utc),
    }

    try:
        get_table().create_entity(entity)
    except KeyError:
        logging.exception("STORAGE_CONNECTION_STRING mangler")
        return respond(500, {"error": "Søknaden ble ikke lagret. Prøv igjen om litt.", "code": "MISSING_SETTING"})
    except ResourceNotFoundError:
        logging.exception("Tabellen finnes ikke")
        return respond(500, {"error": "Søknaden ble ikke lagret. Prøv igjen om litt.", "code": "TABLE_NOT_FOUND"})
    except Exception:
        logging.exception("Kunne ikke lagre søknaden")
        return respond(500, {"error": "Søknaden ble ikke lagret. Prøv igjen om litt.", "code": "SAVE_FAILED"})

    return respond(200, {"ok": True})
