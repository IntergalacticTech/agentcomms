# core/api/personas_handler.py
"""Personas API handler — org-scoped identity profiles.

Routes (all org-scoped):
  POST   /v1/personas                          — create; pass generate=true to
                                                 fill missing fields via Bedrock
  GET    /v1/personas                          — list
  GET    /v1/personas/{id}                     — get single persona
  PATCH  /v1/personas/{id}                     — merge-update
  DELETE /v1/personas/{id}                     — delete (204)
  POST   /v1/agents/{agent_id}/personas        — associate persona → agent
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.api._common import (
    Caller, err, get_repo, no_content, ok, parse_body, require_org_scope,
)
from core.data.models import Persona
from core.data.ulid_ import new_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _persona_response(p: Persona) -> dict:
    return {
        "persona_id": p.persona_id,
        "org_id": p.org_id,
        "name": p.name,
        "address": p.address,
        "dob": p.dob,
        "phone": p.phone,
        "email": p.email,
        "metadata": p.metadata,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _generate_persona_fields(hint: str | None) -> dict:
    """Call Bedrock (Haiku) to generate a plausible synthetic persona.

    Raises ImportError (→ 501) if generation is unavailable — either because
    the bedrock_client module is missing or because the Bedrock service cannot
    be reached (no credentials, throttle, etc.).
    """
    try:
        from core.ai import bedrock_client
        return bedrock_client.generate_persona(hint=hint)
    except ImportError:
        raise ImportError("generation not enabled — enable AI features")
    except Exception as exc:
        raise ImportError(f"generation not enabled — {exc}") from exc


# ---------------------------------------------------------------------------
# Route implementations
# ---------------------------------------------------------------------------

def _create(caller: Caller, body: dict, repo) -> dict:
    should_generate = bool(body.get("generate"))

    if should_generate:
        try:
            generated = _generate_persona_fields(hint=body.get("hint"))
        except ImportError as exc:
            return err(str(exc), status=501)
        except Exception as exc:  # pragma: no cover
            return err(f"Persona generation failed: {exc}", status=500)
        # Merge generated fields; caller-provided fields take precedence
        merged = {**generated, **{k: v for k, v in body.items() if v is not None and k not in ("generate", "hint")}}
        body = merged

    name = (body.get("name") or "").strip()
    if not name:
        return err("'name' is required (or pass generate=true to have one produced for you)")

    persona_id = new_id("per")
    now = datetime.now(timezone.utc)
    persona = Persona(
        persona_id=persona_id,
        org_id=caller.org_id,
        name=name,
        address=body.get("address") or None,
        dob=body.get("dob") or None,
        phone=body.get("phone") or None,
        email=body.get("email") or None,
        metadata=body.get("metadata") or {},
        created_at=now,
        updated_at=now,
    )
    repo.put_persona(persona)
    return ok(_persona_response(persona), status=201)


def _list(caller: Caller, event: dict, repo) -> dict:
    qs = event.get("queryStringParameters") or {}
    limit = int(qs.get("limit", 100))
    personas = repo.list_personas(org_id=caller.org_id, limit=limit)
    return ok({"personas": [_persona_response(p) for p in personas]})


def _get(caller: Caller, persona_id: str, repo) -> dict:
    persona = repo.get_persona(org_id=caller.org_id, persona_id=persona_id)
    if not persona:
        return err("Persona not found", status=404)
    return ok(_persona_response(persona))


def _patch(caller: Caller, persona_id: str, body: dict, repo) -> dict:
    persona = repo.get_persona(org_id=caller.org_id, persona_id=persona_id)
    if not persona:
        return err("Persona not found", status=404)

    allowed = {"name", "address", "dob", "phone", "email", "metadata"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return err("No valid fields to update")

    updated = persona.model_copy(update={**updates, "updated_at": datetime.now(timezone.utc)})
    repo.put_persona(updated)
    return ok(_persona_response(updated))


def _delete(caller: Caller, persona_id: str, repo) -> dict:
    existing = repo.get_persona(org_id=caller.org_id, persona_id=persona_id)
    if not existing:
        return err("Persona not found", status=404)
    repo.delete_persona(org_id=caller.org_id, persona_id=persona_id)
    return no_content()


def _associate(caller: Caller, agent_id: str, body: dict, repo) -> dict:
    """POST /v1/agents/{agent_id}/personas — set agent.metadata.persona_id."""
    persona_id = (body.get("persona_id") or "").strip()
    if not persona_id:
        return err("'persona_id' is required")

    # Verify the persona exists in this org
    persona = repo.get_persona(org_id=caller.org_id, persona_id=persona_id)
    if not persona:
        return err("Persona not found", status=404)

    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if not agent:
        return err("Agent not found", status=404)

    updated_agent = agent.model_copy(
        update={
            "metadata": {**agent.metadata, "persona_id": persona_id},
            "updated_at": datetime.now(timezone.utc),
        }
    )
    repo.put_agent(updated_agent)
    return ok({
        "agent_id": updated_agent.agent_id,
        "name": updated_agent.name,
        "metadata": updated_agent.metadata,
    })


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    caller = Caller.from_event(event)

    if denied := require_org_scope(caller):
        return denied

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}

    repo = get_repo()

    # POST /v1/agents/{agent_id}/personas
    if method == "POST" and pp.get("agent_id") and path.endswith("/personas"):
        body = parse_body(event)
        return _associate(caller, pp["agent_id"], body, repo)

    persona_id = pp.get("id", "")

    # GET /v1/personas/{id}
    if method == "GET" and persona_id:
        return _get(caller, persona_id, repo)

    # GET /v1/personas
    if method == "GET":
        return _list(caller, event, repo)

    # POST /v1/personas
    if method == "POST":
        body = parse_body(event)
        return _create(caller, body, repo)

    # PATCH /v1/personas/{id}
    if method == "PATCH" and persona_id:
        body = parse_body(event)
        return _patch(caller, persona_id, body, repo)

    # DELETE /v1/personas/{id}
    if method == "DELETE" and persona_id:
        return _delete(caller, persona_id, repo)

    return err("Not found", status=404)
