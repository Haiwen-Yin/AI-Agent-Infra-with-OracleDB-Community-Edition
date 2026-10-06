"""Conservative budgets and source-bound extractive context derivations."""
import json
from . import connection, identity_api, continuity_assembly as assembly
from .connection_crypto import encrypt_section, decrypt_section
from .agent_extension_contracts import bounded_json, digest, identifier, canonical, row

REQUIRED_FIELDS = frozenset({"goal", "constraints", "decisions", "incomplete_work", "next_steps", "acceptance_criteria", "pending_actions", "open_questions", "objective", "unfinished_work", "requirements", "obligations", "blockers", "pending_approvals", "completion_criteria"})


def _obligations(value, path=()):
    """Retain each obligation and its source path, including nested handoffs."""
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in REQUIRED_FIELDS:
                result.append({"path": [*path, key], "value": item})
            else:
                result.extend(_obligations(item, (*path, key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_obligations(item, (*path, index)))
    return result


def budget_plan(context_window, output_reserve, instruction_bytes, available_bytes):
    values = (context_window, output_reserve, instruction_bytes, available_bytes)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values) or context_window < 1:
        raise ValueError("Context budget values must be bounded nonnegative integers")
    if context_window > 1000000 or output_reserve >= context_window:
        raise ValueError("Invalid context window or output reserve")
    available = max(0, context_window - output_reserve - instruction_bytes)
    return {"context_window": context_window, "output_reserve": output_reserve, "instruction_upper_bound": instruction_bytes,
            "source_budget": available, "available_source_bytes": available_bytes,
            "derivation_required": available_bytes > available, "count_method": "UTF8_UPPER_BOUND"}


def extract(source_text, budget):
    """Preserve structured obligations verbatim; never invent model summaries."""
    parts, preserved = [], []
    for text in source_text.split("\n\n"):
        try:
            value = json.loads(text)
        except ValueError:
            parts.append({"source_excerpt": text})
            continue
        if isinstance(value, dict):
            required = {key: item for key, item in value.items() if key in REQUIRED_FIELDS}
            if required:
                preserved.append(required)
            nested = _obligations({key: item for key, item in value.items() if key not in REQUIRED_FIELDS})
            if nested:
                preserved.append({"nested_obligations": nested})
            parts.append({key: item for key, item in value.items() if key not in REQUIRED_FIELDS})
        else:
            parts.append({"source_excerpt": value})
    result = {"method": "EXTRACTIVE_FIELDS_UTF8", "preserved_obligations": preserved, "selected_context": []}
    if len(canonical(result).encode()) > budget:
        raise ValueError("Mandatory constraints and unfinished work do not fit; increase the budget")
    for part in parts:
        candidate = {**result, "selected_context": [*result["selected_context"], part]}
        if len(canonical(candidate).encode()) <= budget:
            result = candidate
    if not preserved and not result["selected_context"]:
        raise ValueError("Source cannot be represented safely within this budget")
    return result


def derive(actor, assembly_id, token_budget, *, transaction=None):
    if not isinstance(token_budget, int) or isinstance(token_budget, bool) or not 128 <= token_budget <= 1000000:
        raise ValueError("Derivation budget must be between 128 and 1000000")
    def perform(tx):
        source = assembly._read(tx, actor, assembly_id)
        content = extract(source["text"], token_budget)
        content_hash = digest(content)
        root = row(tx.query_one("SELECT SECURITY_DOMAIN_ID FROM CX_CONTEXT_ASSEMBLIES WHERE ASSEMBLY_ID=:assembly", {"assembly": assembly_id}))
        derivation = identifier("CD")
        tx.execute("INSERT INTO CX_CONTEXT_DERIVATIONS(DERIVATION_ID,ASSEMBLY_ID,ACTOR_ID,SECURITY_DOMAIN_ID,SOURCE_DIGEST,CONTENT_DIGEST,TOKEN_BUDGET,METHOD_KEY,CONTENT_CIPHER) VALUES(:derivation,:assembly,:actor,:domain,:source,:digest,:budget,'EXTRACTIVE_FIELDS_UTF8',:cipher)",
            {"derivation": derivation, "assembly": assembly_id, "actor": actor, "domain": root["security_domain_id"], "source": source["content_digest"], "digest": content_hash, "budget": token_budget, "cipher": encrypt_section({"content": content})})
        for item in source["items"]:
            tx.execute("INSERT INTO CX_CONTEXT_DERIVED_SOURCES(DERIVATION_ID,ASSEMBLY_ID,ITEM_NO) VALUES(:derivation,:assembly,:item_no)",
                {"derivation": derivation, "assembly": assembly_id, "item_no": int(item["item_no"])})
        identity_api._audit_tx(tx, actor, "CONTEXT_DERIVED", "CONTEXT_DERIVATION", derivation, "ALLOW", "Source-bound extractive derivation")
        return {"derivation_id": derivation, "content_digest": content_hash, "source_digest": source["content_digest"], "content": content,
                "rendered_upper_bound": len(canonical(content).encode()), "token_budget": token_budget}
    return perform(transaction) if transaction is not None else connection.execute_transaction_callback(perform)


def read(actor, derivation_id, *, transaction=None):
    def perform(tx):
        record = row(tx.query_one("SELECT * FROM CX_CONTEXT_DERIVATIONS WHERE DERIVATION_ID=:derivation AND ACTOR_ID=:actor", {"derivation": derivation_id, "actor": actor}))
        if not record:
            raise PermissionError("Derived context access denied")
        # Rechecking every original source also catches revoked publications,
        # changed source digests, current domain authority and assembly expiry.
        source = assembly._read(tx, actor, record["assembly_id"])
        links = [row(item) for item in tx.query("SELECT ASSEMBLY_ID,ITEM_NO FROM CX_CONTEXT_DERIVED_SOURCES WHERE DERIVATION_ID=:derivation ORDER BY ITEM_NO", {"derivation": derivation_id})]
        if source["content_digest"] != record["source_digest"] or links != [{"assembly_id": record["assembly_id"], "item_no": int(item["item_no"])} for item in source["items"]]:
            raise ValueError("Derivation source lineage mismatch")
        content = decrypt_section(record["content_cipher"])["content"]
        if digest(content) != record["content_digest"] or len(canonical(content).encode()) > int(record["token_budget"]):
            raise ValueError("Derived context failed integrity validation")
        return {"derivation_id": derivation_id, "assembly_id": record["assembly_id"], "content": content, "content_digest": record["content_digest"], "token_budget": int(record["token_budget"])}
    return perform(transaction) if transaction is not None else connection.execute_transaction_callback(perform)
