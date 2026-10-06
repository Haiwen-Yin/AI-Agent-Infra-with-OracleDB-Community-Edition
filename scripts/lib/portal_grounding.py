"""One knowledge-first answer pipeline for both Portal response transports."""
from __future__ import annotations

import json
from typing import Any
from . import connection, content_security, identity_api, knowledge_grounding, native_runtime, answer_planning


def policy() -> dict[str, Any]:
    mode_column = '"MODE"' if str(connection.DATABASE_DIALECT).lower() == "oracle" else "MODE"
    raw = connection.execute_query_one(
        "SELECT POLICY_ID," + mode_column + ",ALLOW_MODEL_SUPPLEMENT,DISCLOSURE_PROFILES_JSON,VERSION "
        "FROM CX_PORTAL_KNOWLEDGE_POLICY WHERE POLICY_ID='DEFAULT'", {})
    if not raw:
        raise knowledge_grounding.GroundingError("Portal knowledge policy is unavailable")
    row = {k.lower(): v for k, v in raw.items()}
    row["version"] = int(row["version"])
    if row["mode"] not in {"KNOWLEDGE_FIRST", "KNOWLEDGE_ONLY"}:
        raise knowledge_grounding.GroundingError("Portal knowledge policy is invalid")
    row["disclosure_profiles"] = json.loads(str(row.pop("disclosure_profiles_json") or "[]"))
    return row


def set_policy(actor: str, mode: str, allow_model_supplement: bool, disclosure_profiles: list[str], expected_version: int, reason: str) -> dict[str, Any]:
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("Platform management permission is required")
    if (mode not in {"KNOWLEDGE_FIRST", "KNOWLEDGE_ONLY"}
            or type(allow_model_supplement) is not bool
            or type(expected_version) is not int or expected_version < 1
            or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000
            or not isinstance(disclosure_profiles, list) or len(disclosure_profiles) > 50
            or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in disclosure_profiles)):
        raise ValueError("Knowledge policy is invalid")
    if mode == "KNOWLEDGE_ONLY" and allow_model_supplement:
        raise ValueError("Knowledge-only policy cannot allow model supplementation")
    def work(tx):
        current = tx.query_one("SELECT VERSION FROM CX_PORTAL_KNOWLEDGE_POLICY WHERE POLICY_ID='DEFAULT' FOR UPDATE", {})
        if not current or int(next(iter(current.values()))) != expected_version:
            raise knowledge_grounding.GroundingError("Knowledge policy changed concurrently")
        for profile in disclosure_profiles:
            if not tx.query_one("SELECT PROFILE_ID FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": profile}):
                raise ValueError("Knowledge disclosure profile is unavailable")
        mode_column = '"MODE"' if str(connection.DATABASE_DIALECT).lower() == "oracle" else "MODE"
        changed = tx.execute("UPDATE CX_PORTAL_KNOWLEDGE_POLICY SET " + mode_column + "=:policy_mode,ALLOW_MODEL_SUPPLEMENT=:supplement,"
            "DISCLOSURE_PROFILES_JSON=:profiles,VERSION=VERSION+1,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP,REASON=:reason "
            "WHERE POLICY_ID='DEFAULT' AND VERSION=:expected", {"policy_mode": mode, "supplement": "Y" if allow_model_supplement else "N",
                "profiles": json.dumps(sorted(set(disclosure_profiles))), "actor": actor, "reason": reason[:2000], "expected": expected_version})
        if changed != 1:
            raise knowledge_grounding.GroundingError("Knowledge policy changed concurrently")
        identity_api._audit_tx(tx, actor, "PORTAL_KNOWLEDGE_POLICY", "POLICY", "DEFAULT", "ALLOW", reason)
        return {"version": expected_version + 1, "mode": mode}
    return connection.execute_transaction_callback(work)


def answer(session: dict[str, Any], message: str, profile: dict[str, Any], *, supplement: bool = False, entity_ids: list[str] | None = None) -> dict[str, Any]:
    actor, agent = str(session.get("principal_id") or ""), str(session.get("agent_id") or "")
    content_security.enforce(message, "USER_INPUT")
    configured = policy()
    result = answer_planning.retrieve(actor, agent, message, entity_ids=entity_ids)
    sources = result["items"]
    effective_policy = dict(configured, allow_model_supplement=configured["allow_model_supplement"] if supplement else "N")
    planned = answer_planning.prepare(message, str(profile.get("profile_id") or ""), effective_policy, result)
    citations, source = planned["citations"], planned["answer_source"]
    reply = planned["knowledge_reply"]
    if reply is None:
        reply = native_runtime._call_llm(profile, planned["messages"])["content"]
    content_security.enforce(reply, "OUTPUT")
    knowledge_grounding.require_reader(actor, agent)
    for item in citations:
        knowledge_grounding.citation(actor, agent, item["entity_id"], item["digest"])
    if policy()["version"] != configured["version"]:
        raise knowledge_grounding.GroundingError("Knowledge policy changed during answer generation")
    return {"reply": reply, "citations": citations, "answer_source": source,
            "retrieval_status": result["status"], "policy_version": configured["version"]}
