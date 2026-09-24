"""AGY-Herdr Software Factory v8.0.0 — Context Efficiency Core Module.

Implements:
1. ContextCompiler: Canonical, immutable, bounded, role-specific context packets.
2. ContextSource boundary (FilesystemGitContextSource).
3. Anchor model and required-anchor recall gate (required_anchor_recall == 1.0).
4. HandoffPacket: Bounded cross-task semantic contracts (<= 4096 bytes).
5. Stable Prefix architecture with canonical ordering, hashing, and byte tracking.
6. ContextPolicy with evidence-derived budgets (soft/hard) and deterministic pruning.
7. Context telemetry, redundancy chunk analysis, and inspection CLI support.
8. Derived requirement traceability, auditing, and orphan rejection.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import secrets
import shlex
import subprocess
import threading
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Global Constants
COMPILER_VERSION = "8.0.0"
SCHEMA_VERSION = "8.0.0"
STABLE_PREFIX_VERSION = "1.0.0"
MAX_SEMANTIC_HANDOFF_BYTES = 4096
DEFAULT_MAX_INLINE_BYTES = 4096


# Custom Exceptions
class ContextError(Exception):
    """Base exception for all Context Compiler errors."""
    pass


class ContextAnchorMissingError(ContextError):
    """Raised when required anchor recall is less than 1.0."""
    pass


class ContextBudgetExceededError(ContextError):
    """Raised when context packet exceeds hard budget after all deterministic pruning."""
    pass


class StaleContextPacketError(ContextError):
    """Raised when a context packet is detected as stale due to source changes."""
    pass


class OrphanDerivedRequirementError(ContextError):
    """Raised when a derived requirement does not trace to any explicit criterion or invariant."""
    pass


class MalformedContextPacketError(ContextError):
    """Raised when context packet input or schema is malformed."""
    pass


def sha256_text(text: str) -> str:
    """Computes SHA-256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Computes SHA-256 hash of raw bytes."""
    return hashlib.sha256(data).hexdigest()


KNOWN_SECRET_ENV_VARS = [
    "OPENAI_API_KEY",
    "FACTORY_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_TOKEN",
    "OPENROUTER_API_KEY",
    "OPENCODE_API_KEY",
    "HERDR_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GCP_SERVICE_ACCOUNT_KEY",
    "DATABASE_URL",
    "VAULT_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
]

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"fk-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"gh[posr]_[a-zA-Z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\.\-]{20,}", re.IGNORECASE),
    re.compile(r"glpat-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^:@/\s]+:[^:@/\s]+@", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+ KEY-----[\s\S]+?-----END [A-Z ]+ KEY-----"),
]

ENV_SECRET_KEY_PATTERN = re.compile(r"(?:_KEY|_TOKEN|_SECRET|_PASSWORD|_PASSWD|_AUTH|_CREDENTIAL|_PRIVATE)$", re.IGNORECASE)

INJECTION_PATTERN = re.compile(
    r"(?i)(ignore\s+all\s+prior\s+instructions"
    r"|disregard\s+(?:all\s+)?(?:prior|previous)\s+instructions"
    r"|forget\s+(?:all\s+)?(?:prior|previous|the\s+above)"
    r"|new\s+instructions:"
    r"|system\s+prompt"
    r"|developer\s+mode"
    r"|override\s+instructions"
    r"|<\|(?:im_start|im_end|system|user|assistant)\|>"
    r"|\[\s*(?:SYSTEM|INST|ASSISTANT)\s*\]"
    r"|<\s*/?\s*system(?:\s+prompt)?\s*>)"
)

_HOMOGLYPH_MAP = str.maketrans({
    'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y', 'х': 'x', 'і': 'i', 'ј': 'j', 'ѕ': 's',
    'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'Х': 'X',
    'Α': 'A', 'Β': 'B', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'H', 'Ι': 'I', 'Κ': 'K', 'Μ': 'M', 'Ν': 'N', 'Ο': 'O', 'Ρ': 'P', 'Τ': 'T', 'Υ': 'Y', 'Χ': 'X',
    'α': 'a', 'β': 'b', 'ε': 'e', 'ι': 'i', 'κ': 'k', 'ν': 'n', 'ο': 'o', 'ρ': 'p', 'τ': 't', 'υ': 'u', 'χ': 'x',
})


def normalize_homoglyphs(text: str) -> str:
    """Normalizes Cyrillic and Greek lookalikes to Latin characters to prevent injection bypass."""
    return text.translate(_HOMOGLYPH_MAP)


# Freeze load-time environment secret snapshot (never re-read os.environ dynamically during redaction)
_INITIAL_SECRET_ENV: dict[str, str] = {}
_SECRET_ENV_LOCK = threading.RLock()

SECRET_SUBKEY_NAMES = {
    "private_key", "private_key_id", "client_secret", "token", "access_token",
    "refresh_token", "secret", "password", "passwd", "api_key", "apikey",
    "auth", "credential", "credentials"
}


def _extract_json_secrets(prefix: str, obj: Any) -> dict[str, str]:
    """Extracts string values from JSON credential structures where keys match sensitive patterns."""
    extracted = {}
    if isinstance(obj, dict):
        for sub_k, sub_v in obj.items():
            sk_str = str(sub_k).lower()
            combined = f"{prefix}_{str(sub_k).upper()}"
            is_sensitive = (sk_str in SECRET_SUBKEY_NAMES or ENV_SECRET_KEY_PATTERN.search(str(sub_k)) is not None)
            if isinstance(sub_v, str):
                s = sub_v.strip()
                if is_sensitive and len(s) >= 6:
                    extracted[combined] = s
            elif isinstance(sub_v, (dict, list)):
                extracted.update(_extract_json_secrets(combined, sub_v))
    elif isinstance(obj, list):
        for idx, sub_item in enumerate(obj):
            combined = f"{prefix}_{idx}"
            if isinstance(sub_item, (dict, list)):
                extracted.update(_extract_json_secrets(combined, sub_item))
    return extracted


def snapshot_secret_env() -> dict[str, str]:
    """Snapshots sensitive environment variables with length >= 6 into the frozen snapshot.

    Idempotent and safe to invoke multiple times; always operates under _SECRET_ENV_LOCK.
    """
    with _SECRET_ENV_LOCK:
        for _k, _v in os.environ.items():
            if _k in KNOWN_SECRET_ENV_VARS or ENV_SECRET_KEY_PATTERN.search(_k):
                stripped = _v.strip()
                if stripped and len(stripped) >= 6:
                    clean_v = normalize_homoglyphs(unicodedata.normalize("NFKC", stripped))
                    _INITIAL_SECRET_ENV[_k] = clean_v
                    # If value is a JSON blob (e.g. GCP_SERVICE_ACCOUNT_KEY), extract all inner string values
                    if stripped.startswith("{") and stripped.endswith("}"):
                        try:
                            parsed = json.loads(stripped)
                            _INITIAL_SECRET_ENV.update(_extract_json_secrets(_k, parsed))
                        except Exception:
                            pass
        return dict(_INITIAL_SECRET_ENV)


def register_secret_env(key: str, val: str) -> None:
    """Registers a sensitive environment variable into the frozen snapshot for testing or runtime auth."""
    if (key in KNOWN_SECRET_ENV_VARS or ENV_SECRET_KEY_PATTERN.search(key)) and val:
        stripped = val.strip()
        if len(stripped) >= 6:
            clean_v = normalize_homoglyphs(unicodedata.normalize("NFKC", stripped))
            with _SECRET_ENV_LOCK:
                _INITIAL_SECRET_ENV[key] = clean_v
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        parsed = json.loads(stripped)
                        _INITIAL_SECRET_ENV.update(_extract_json_secrets(key, parsed))
                    except Exception:
                        pass


def get_secret_env_fingerprint() -> str:
    """Returns SHA-256 fingerprint of registered secret env keys to detect secret registration drift."""
    with _SECRET_ENV_LOCK:
        keys_summary = "|".join(f"{k}:{len(v)}" for k, v in sorted(_INITIAL_SECRET_ENV.items()))
    return sha256_text(keys_summary)


# Initial module-load snapshot
snapshot_secret_env()


def redact_secrets(val: Any) -> Any:
    """Recursively redacts secret API keys, tokens, and sensitive env vars across values, preserving dict structure."""
    if isinstance(val, str):
        res = val
        with _SECRET_ENV_LOCK:
            sorted_secrets = sorted(_INITIAL_SECRET_ENV.items(), key=lambda x: len(x[1]), reverse=True)
            for env_k, env_v in sorted_secrets:
                if env_v:
                    res = res.replace(env_v, f"[REDACTED_{env_k}]")
            for pat in SECRET_PATTERNS:
                res = pat.sub("[REDACTED_SECRET]", res)
            return res
    elif isinstance(val, list):
        return [redact_secrets(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(redact_secrets(item) for item in val)
    elif isinstance(val, dict):
        return {redact_secrets(k) if isinstance(k, str) else k: redact_secrets(v) for k, v in val.items()}
    return val


VALID_PROVENANCES = {"USER_EXPLICIT", "DERIVED", "MOCK", "TRANSPORT_ONLY", "REAL"}


def validate_criterion_provenance(criterion: dict) -> None:
    """Validates that criterion provenance is a valid member of the closed provenance enum."""
    cid = criterion.get("id", "unknown")
    prov = criterion.get("provenance")
    if not prov or prov not in VALID_PROVENANCES:
        raise ContextError(
            f"Criterion '{cid}' has invalid or missing provenance: '{prov}'. Must be one of {sorted(VALID_PROVENANCES)}"
        )


def canonical_json_dump(obj: Any) -> str:
    """Produces canonical deterministic JSON string with sorted keys."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True)


# ==============================================================================
# 1. ANCHOR ARCHITECTURE
# ==============================================================================

VALID_ANCHOR_TYPES = {
    "requirement",
    "invariant",
    "interface_contract",
    "file_reference",
    "dependency_decision",
    "validation",
    "allowed_path",
    "protected_path",
}


@dataclasses.dataclass
class Anchor:
    """A unit of critical context that must survive reduction and pruning."""
    anchor_id: str
    anchor_type: str
    source: str
    source_hash: str
    content: str
    required: bool = True

    def __post_init__(self):
        if self.anchor_type not in VALID_ANCHOR_TYPES:
            raise MalformedContextPacketError(
                f"Invalid anchor_type '{self.anchor_type}'. Must be one of {sorted(VALID_ANCHOR_TYPES)}"
            )
        if not self.anchor_id:
            raise MalformedContextPacketError("Anchor anchor_id cannot be empty")
        if not self.source:
            raise MalformedContextPacketError("Anchor source cannot be empty")
        if not self.content or not self.content.strip():
            raise MalformedContextPacketError(f"Anchor '{self.anchor_id}' content cannot be empty")
        # source_hash represents caller-authoritative cryptographic provenance of the anchor origin.
        # It must be a valid 64-character SHA-256 hex string provided by caller (no silent auto-derivation).
        if not self.source_hash or not isinstance(self.source_hash, str) or len(self.source_hash) != 64 or not all(c in "0123456789abcdefABCDEF" for c in self.source_hash):
            raise MalformedContextPacketError(
                f"Anchor source_hash must be a valid 64-character hex SHA-256 string (got {repr(self.source_hash)})"
            )

    def to_dict(self) -> dict:
        return {
            "anchor_id": self.anchor_id,
            "type": self.anchor_type,
            "source": self.source,
            "source_hash": self.source_hash,
            "content": self.content,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Anchor:
        return cls(
            anchor_id=data["anchor_id"],
            anchor_type=data.get("type", data.get("anchor_type", "requirement")),
            source=data["source"],
            source_hash=data["source_hash"],
            content=data.get("content", ""),
            required=data.get("required", True),
        )


def calculate_anchor_recall(
    available_anchors: List[Anchor], required_anchors: List[Anchor]
) -> Tuple[float, List[str]]:
    """Calculates recall ratio for required anchors: included_required / total_required.

    Returns:
        (recall_ratio, missing_anchor_ids)
    """
    total_req = [a for a in required_anchors if a.required]
    if not total_req:
        return 1.0, []

    avail_map = {a.anchor_id: a for a in available_anchors}
    missing = []
    included_count = 0

    for req in total_req:
        found = avail_map.get(req.anchor_id)
        if found:
            # Check source hash consistency
            if found.source_hash == req.source_hash:
                included_count += 1
            else:
                missing.append(f"{req.anchor_id} (hash_mismatch)")
        else:
            missing.append(req.anchor_id)

    recall = included_count / len(total_req)
    return recall, missing


def verify_required_anchors(anchors: List[Anchor], full_rendered_prompt: str, context_label: str = "Prompt") -> None:
    """Strictly verifies required anchor recall and secondary exact substring gates for file and validation anchors."""
    recall, missing = calculate_rendered_anchor_recall(anchors, full_rendered_prompt)
    if recall < 1.0:
        raise ContextAnchorMissingError(
            f"CONTEXT_ANCHOR_MISSING: {context_label} missing required anchors: {missing}"
        )

    # Secondary exact-substring gate for required file_reference anchors
    req_file_anchors = [a for a in anchors if a.required and a.anchor_type == "file_reference"]
    for fa in req_file_anchors:
        if fa.content not in full_rendered_prompt:
            raise ContextAnchorMissingError(
                f"CONTEXT_ANCHOR_MISSING: {context_label} required file anchor '{fa.content}' dropped during compilation/pruning"
            )

    # Secondary exact-substring gate for required validation anchors
    req_val_anchors = [a for a in anchors if a.required and a.anchor_type == "validation"]
    for va in req_val_anchors:
        if va.content not in full_rendered_prompt:
            raise ContextAnchorMissingError(
                f"CONTEXT_ANCHOR_MISSING: {context_label} required validation anchor '{va.content}' dropped during compilation/pruning"
            )


def calculate_rendered_anchor_recall(
    required_anchors: List[Anchor], rendered_text: str
) -> Tuple[float, List[str]]:
    """Calculates recall ratio for required anchors in rendered prompt text: included / total_required.

    Fails closed if any required anchor is omitted from the rendered text.
    Uses strict boundary-aware matching to avoid false substring collisions.
    Returns:
        (recall_ratio, missing_anchor_ids)
    """
    total_req = [a for a in required_anchors if a.required]
    if not total_req:
        return 1.0, []

    missing = []
    included_count = 0
    for req in total_req:
        content = req.content.strip()
        if not content:
            missing.append(req.anchor_id)
            continue
        found = False
        # Strict boundary matching depending on anchor type
        if getattr(req, "anchor_type", "") == "validation":
            found = bool(re.search(r"`" + re.escape(content) + r"`", rendered_text)) or bool(re.search(r"(?m)^[\s*\-]*`?" + re.escape(content) + r"`?", rendered_text))
        elif getattr(req, "anchor_type", "") in ("file_reference", "allowed_path", "protected_path"):
            file_pattern = r"(?<![a-zA-Z0-9_./\-])" + re.escape(content) + r"(?![a-zA-Z0-9_/\-]|\.[a-zA-Z0-9])"
            found = bool(re.search(file_pattern, rendered_text))
        else:
            pattern = r"(?<![a-zA-Z0-9_])" + re.escape(content) + r"(?![a-zA-Z0-9_]|/[a-zA-Z0-9_]|\.[a-zA-Z0-9])"
            found = bool(re.search(pattern, rendered_text))
        if found:
            included_count += 1
        else:
            missing.append(req.anchor_id)

    recall = included_count / len(total_req)
    return recall, missing


# ==============================================================================
# 2. HANDOFF PACKET ARCHITECTURE
# ==============================================================================

@dataclasses.dataclass
class HandoffPacket:
    """Structured semantic and deterministic handoff produced by a completed task attempt."""
    handoff_id: str
    producer_task_id: str
    producer_attempt: int
    changed_paths: List[str]
    satisfied_criteria: List[str]
    commit: Optional[str] = None
    contracts: Union[str, dict] = ""
    decisions: Union[str, List[str]] = ""
    consumer_notes: str = ""
    known_risks: Union[str, List[str]] = ""
    validation_result: dict = dataclasses.field(default_factory=lambda: {"passed": True})
    handoff_bytes: int = 0
    handoff_hash: str = ""
    created_at: str = ""
    compacted: bool = False
    original_handoff_hash: str = ""
    synthesis_source: str = "REAL"
    contracts_truncated_to_string: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not self.handoff_hash:
            self.enforce_semantic_bounds()
        else:
            # Hash verification is strictly performed pre-instantiation in HandoffPacket.from_dict()
            actual_bytes = len(canonical_json_dump(self.to_dict()).encode("utf-8"))
            if actual_bytes > MAX_SEMANTIC_HANDOFF_BYTES:
                raise ContextError(f"Handoff packet {self.handoff_id} structural payload exceeds limit: {actual_bytes} > {MAX_SEMANTIC_HANDOFF_BYTES}")
            if self.handoff_bytes > MAX_SEMANTIC_HANDOFF_BYTES:
                raise ContextError(f"Handoff packet {self.handoff_id} structural payload exceeds limit: {self.handoff_bytes} > {MAX_SEMANTIC_HANDOFF_BYTES}")

    def enforce_semantic_bounds(self, max_bytes: int = MAX_SEMANTIC_HANDOFF_BYTES) -> None:
        """Enforces hard bound on semantic free-text fields without losing deterministic facts."""
        # Bound consumer_notes
        if isinstance(self.consumer_notes, str) and len(self.consumer_notes.encode("utf-8")) > max_bytes:
            encoded = self.consumer_notes.encode("utf-8")[:max_bytes - 32]
            self.consumer_notes = encoded.decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]"

        # Bound contracts if string or dict
        if isinstance(self.contracts, str) and len(self.contracts.encode("utf-8")) > max_bytes:
            encoded = self.contracts.encode("utf-8")[:max_bytes - 32]
            self.contracts = encoded.decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]"
        elif isinstance(self.contracts, dict):
            c_str = canonical_json_dump(self.contracts)
            if len(c_str.encode("utf-8")) > max_bytes:
                encoded = c_str.encode("utf-8")[:max_bytes - 32]
                self.contracts = encoded.decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]"
                self.contracts_truncated_to_string = True

        # Bound decisions
        if isinstance(self.decisions, str) and len(self.decisions.encode("utf-8")) > max_bytes:
            encoded = self.decisions.encode("utf-8")[:max_bytes - 32]
            self.decisions = encoded.decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]"
        elif isinstance(self.decisions, list):
            bounded_decisions = []
            cur_b = 0
            for item in self.decisions:
                item_str = str(item)
                item_len = len(item_str.encode("utf-8"))
                if cur_b + item_len > max_bytes:
                    bounded_decisions.append("[TRUNCATED:BOUND]")
                    break
                bounded_decisions.append(item_str)
                cur_b += item_len
            self.decisions = bounded_decisions

        # Bound known_risks
        if isinstance(self.known_risks, str) and len(self.known_risks.encode("utf-8")) > max_bytes:
            encoded = self.known_risks.encode("utf-8")[:max_bytes - 32]
            self.known_risks = encoded.decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]"
        elif isinstance(self.known_risks, list):
            bounded_risks = []
            cur_b = 0
            for item in self.known_risks:
                item_str = str(item)
                item_len = len(item_str.encode("utf-8"))
                if cur_b + item_len > max_bytes:
                    bounded_risks.append("[TRUNCATED:BOUND]")
                    break
                bounded_risks.append(item_str)
                cur_b += item_len
            self.known_risks = bounded_risks

        # Enforce total aggregate bound proportionally across all four free-text fields
        # Reserve envelope headroom so the overall serialized JSON remains <= max_bytes
        ft_budget = max(512, max_bytes - 768)

        # Initial proportional scale down if massive initial excess
        init_parts = {
            "consumer_notes": self.consumer_notes if isinstance(self.consumer_notes, str) else "",
            "known_risks": self.known_risks if isinstance(self.known_risks, str) else "\n".join(self.known_risks),
            "decisions": self.decisions if isinstance(self.decisions, str) else "\n".join(self.decisions),
            "contracts": self.contracts if isinstance(self.contracts, str) else canonical_json_dump(self.contracts),
        }
        init_ft_bytes = sum(len(v.encode("utf-8")) for v in init_parts.values())
        if init_ft_bytes > ft_budget:
            scale = ft_budget / float(init_ft_bytes)
            for f_name, v_str in init_parts.items():
                cur = getattr(self, f_name)
                alloc_b = max(64, int(len(v_str.encode("utf-8")) * scale) - 32)
                if isinstance(cur, str):
                    setattr(self, f_name, cur.encode("utf-8")[:alloc_b].decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]")
                elif isinstance(cur, dict):
                    setattr(self, f_name, canonical_json_dump(cur).encode("utf-8")[:alloc_b].decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]")
                    if f_name == "contracts":
                        self.contracts_truncated_to_string = True

        for _ in range(200):
            ft_parts = {
                "consumer_notes": self.consumer_notes if isinstance(self.consumer_notes, str) else "",
                "known_risks": self.known_risks if isinstance(self.known_risks, str) else "\n".join(self.known_risks),
                "decisions": self.decisions if isinstance(self.decisions, str) else "\n".join(self.decisions),
                "contracts": self.contracts if isinstance(self.contracts, str) else canonical_json_dump(self.contracts),
            }
            total_ft_bytes = sum(len(v.encode("utf-8")) for v in ft_parts.values())
            if total_ft_bytes <= ft_budget:
                break
            excess = total_ft_bytes - ft_budget
            largest_field = max(ft_parts.keys(), key=lambda k: len(ft_parts[k].encode("utf-8")))
            cur_val = getattr(self, largest_field)
            if isinstance(cur_val, str):
                cur_b = len(cur_val.encode("utf-8"))
                trim_amount = min(cur_b, max(32, excess // 2 + 1))
                new_b = max(0, cur_b - trim_amount)
                new_str = cur_val.encode("utf-8")[:new_b].decode("utf-8", errors="ignore")
                if new_str and not new_str.endswith("[TRUNCATED:BOUND]"):
                    new_str += "\n[TRUNCATED:BOUND]"
                setattr(self, largest_field, new_str)
            elif isinstance(cur_val, dict):
                c_str = canonical_json_dump(cur_val)
                cur_b = len(c_str.encode("utf-8"))
                trim_amount = min(cur_b, max(32, excess // 2 + 1))
                new_b = max(0, cur_b - trim_amount)
                new_str = c_str.encode("utf-8")[:new_b].decode("utf-8", errors="ignore") + "\n[TRUNCATED:BOUND]"
                setattr(self, largest_field, new_str)
                if largest_field == "contracts":
                    self.contracts_truncated_to_string = True
            elif isinstance(cur_val, list):
                if cur_val:
                    cur_val.pop()
                    new_list = [x for x in cur_val if x != "[TRUNCATED:BOUND]"]
                    if new_list:
                        new_list.append("[TRUNCATED:BOUND]")
                    setattr(self, largest_field, new_list)
                else:
                    break

        # Verify total aggregate free-text bytes after convergence loop
        ft_parts = {
            "consumer_notes": self.consumer_notes if isinstance(self.consumer_notes, str) else "",
            "known_risks": self.known_risks if isinstance(self.known_risks, str) else "\n".join(self.known_risks),
            "decisions": self.decisions if isinstance(self.decisions, str) else "\n".join(self.decisions),
            "contracts": self.contracts if isinstance(self.contracts, str) else canonical_json_dump(self.contracts),
        }
        final_ft_bytes = sum(len(v.encode("utf-8")) for v in ft_parts.values())
        if final_ft_bytes > ft_budget:
            per_field = max(64, ft_budget // 4)
            marker = "\n[TRUNCATED:BOUND]"
            marker_b = len(marker.encode("utf-8"))
            alloc = max(16, per_field - marker_b)
            if isinstance(self.consumer_notes, str):
                self.consumer_notes = self.consumer_notes.encode("utf-8")[:alloc].decode("utf-8", errors="ignore") + marker
            if isinstance(self.contracts, str):
                self.contracts = self.contracts.encode("utf-8")[:alloc].decode("utf-8", errors="ignore") + marker
            elif isinstance(self.contracts, dict):
                self.contracts = canonical_json_dump(self.contracts).encode("utf-8")[:alloc].decode("utf-8", errors="ignore") + marker
                self.contracts_truncated_to_string = True
            if isinstance(self.decisions, str):
                self.decisions = self.decisions.encode("utf-8")[:alloc].decode("utf-8", errors="ignore") + marker
            elif isinstance(self.decisions, list):
                self.decisions = [str(d)[:max(16, alloc // 2)] for d in self.decisions[:1]] + ["[TRUNCATED:BOUND]"]
            if isinstance(self.known_risks, str):
                self.known_risks = self.known_risks.encode("utf-8")[:alloc].decode("utf-8", errors="ignore") + marker
            elif isinstance(self.known_risks, list):
                self.known_risks = [str(r)[:max(16, alloc // 2)] for r in self.known_risks[:1]] + ["[TRUNCATED:BOUND]"]

            # Re-verify final_ft_bytes <= ft_budget and guarantee compliance
            post_ft_parts = {
                "consumer_notes": self.consumer_notes if isinstance(self.consumer_notes, str) else "",
                "known_risks": self.known_risks if isinstance(self.known_risks, str) else "\n".join(self.known_risks),
                "decisions": self.decisions if isinstance(self.decisions, str) else "\n".join(self.decisions),
                "contracts": self.contracts if isinstance(self.contracts, str) else canonical_json_dump(self.contracts),
            }
            if sum(len(v.encode("utf-8")) for v in post_ft_parts.values()) > ft_budget:
                cut = max(16, ft_budget // 8)
                self.consumer_notes = self.consumer_notes.encode("utf-8")[:cut].decode("utf-8", errors="ignore") + marker
                if isinstance(self.contracts, dict):
                    self.contracts_truncated_to_string = True
                self.contracts = (self.contracts if isinstance(self.contracts, str) else canonical_json_dump(self.contracts)).encode("utf-8")[:cut].decode("utf-8", errors="ignore") + marker
                self.decisions = ["[TRUNCATED:BOUND]"]
                self.known_risks = ["[TRUNCATED:BOUND]"]

            final_ft_check = sum(
                len(v.encode("utf-8")) for v in [
                    self.consumer_notes if isinstance(self.consumer_notes, str) else "",
                    self.known_risks if isinstance(self.known_risks, str) else "\n".join(self.known_risks),
                    self.decisions if isinstance(self.decisions, str) else "\n".join(self.decisions),
                    self.contracts if isinstance(self.contracts, str) else canonical_json_dump(self.contracts),
                ]
            )
            if final_ft_check > ft_budget:
                raise ContextError(f"HandoffPacket free-text bytes ({final_ft_check}) exceed budget ({ft_budget}) after hard fallback")

        # Bound individual path lengths to 512 bytes
        self.changed_paths = [str(p)[:512] for p in self.changed_paths]

        # Cap structural lists to prevent unbounded growth from mass file changes
        if len(self.changed_paths) > 200:
            truncated_count = len(self.changed_paths) - 200
            self.changed_paths = sorted(self.changed_paths)[:200] + [f"[+{truncated_count} paths truncated]"]
        if len(self.satisfied_criteria) > 100:
            self.satisfied_criteria = sorted(self.satisfied_criteria)[:100]

        # Ensure total serialized size is strictly within max_bytes before computing final handoff_bytes
        for _ in range(20):
            cur_raw_bytes = len(canonical_json_dump(self.to_dict_raw()).encode("utf-8"))
            if cur_raw_bytes <= max_bytes - 256:
                break
            if isinstance(self.decisions, list) and len(self.decisions) > 1:
                self.decisions = self.decisions[:1]
                continue
            if isinstance(self.known_risks, list) and len(self.known_risks) > 1:
                self.known_risks = self.known_risks[:1]
                continue
            if isinstance(self.consumer_notes, str) and len(self.consumer_notes) > 32:
                self.consumer_notes = self.consumer_notes[:32] + "\n[TRUNCATED:BOUND]"
                continue
            if isinstance(self.contracts, str) and len(self.contracts) > 32:
                self.contracts = self.contracts[:32] + "\n[TRUNCATED:BOUND]"
                continue
            if len(self.changed_paths) > 10:
                self.changed_paths = self.changed_paths[:10] + [f"[+{len(self.changed_paths)-10} paths truncated]"]
                continue
            break

        final_raw_bytes = len(canonical_json_dump(self.to_dict_raw()).encode("utf-8"))
        if final_raw_bytes > max_bytes - 128:
            raise ContextError(f"HandoffPacket raw size exceeds headroom bound {max_bytes - 128}: raw size is {final_raw_bytes}")

        # Compute hash once at creation time if not already set
        if not self.handoff_hash:
            raw_repr = canonical_json_dump(self.to_dict_raw())
            self.handoff_hash = sha256_text(raw_repr)

        full_d = self.to_dict_raw()
        full_d["handoff_hash"] = self.handoff_hash
        full_d["handoff_bytes"] = 0
        b = len(canonical_json_dump(full_d).encode("utf-8"))
        for _ in range(20):
            full_d["handoff_bytes"] = b
            b_new = len(canonical_json_dump(full_d).encode("utf-8"))
            if b_new == b:
                break
            b = b_new
        self.handoff_bytes = b
        actual_bytes = len(canonical_json_dump(self.to_dict()).encode("utf-8"))
        if actual_bytes != self.handoff_bytes:
            self.handoff_bytes = actual_bytes
        if self.handoff_bytes > max_bytes:
            raise ContextError(f"Handoff packet {self.handoff_id} structural payload exceeds limit: {self.handoff_bytes} > {max_bytes}")

    def to_dict_raw(self) -> dict:
        d = {
            "schema_version": SCHEMA_VERSION,
            "handoff_id": self.handoff_id,
            "producer_task_id": self.producer_task_id,
            "producer_attempt": self.producer_attempt,
            "commit": self.commit,
            "changed_paths": sorted(self.changed_paths),
            "satisfied_criteria": sorted(self.satisfied_criteria),
            "contracts": self.contracts,
            "decisions": self.decisions,
            "consumer_notes": self.consumer_notes,
            "known_risks": self.known_risks,
            "validation_result": self.validation_result,
            "created_at": self.created_at,
        }
        if self.compacted:
            d["compacted"] = True
            d["original_handoff_hash"] = self.original_handoff_hash
        if self.contracts_truncated_to_string:
            d["contracts_truncated_to_string"] = True
        return d

    def to_dict(self) -> dict:
        d = self.to_dict_raw()
        d["handoff_bytes"] = self.handoff_bytes
        d["handoff_hash"] = self.handoff_hash
        d["synthesis_source"] = getattr(self, "synthesis_source", "REAL")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> HandoffPacket:
        if not d.get("handoff_hash"):
            raise MalformedContextPacketError(
                f"HandoffPacket is missing required handoff_hash field: {d.get('handoff_id', 'unknown')}"
            )
        # Compute and verify hash directly on raw stored fields BEFORE instantiation to prevent mutation prior to verification
        raw_dict = {
            "schema_version": d.get("schema_version", SCHEMA_VERSION),
            "handoff_id": d["handoff_id"],
            "producer_task_id": d["producer_task_id"],
            "producer_attempt": d["producer_attempt"],
            "commit": d.get("commit"),
            "changed_paths": sorted(d.get("changed_paths", [])),
            "satisfied_criteria": sorted(d.get("satisfied_criteria", [])),
            "contracts": d.get("contracts", ""),
            "decisions": d.get("decisions", ""),
            "consumer_notes": d.get("consumer_notes", ""),
            "known_risks": d.get("known_risks", ""),
            "validation_result": d.get("validation_result", {"passed": True}),
            "created_at": d.get("created_at", ""),
        }
        if d.get("compacted"):
            raw_dict["compacted"] = True
            raw_dict["original_handoff_hash"] = d.get("original_handoff_hash", "")
        if d.get("contracts_truncated_to_string"):
            raw_dict["contracts_truncated_to_string"] = True
        computed = sha256_text(canonical_json_dump(raw_dict))
        stored_hash = d["handoff_hash"]
        if computed != stored_hash:
            raise MalformedContextPacketError(
                f"Handoff integrity verification failed for {d.get('handoff_id')}: stored hash {stored_hash[:8]} != computed hash {computed[:8]}"
            )
        hp = cls(
            handoff_id=d["handoff_id"],
            producer_task_id=d["producer_task_id"],
            producer_attempt=d["producer_attempt"],
            commit=d.get("commit"),
            changed_paths=d.get("changed_paths", []),
            satisfied_criteria=d.get("satisfied_criteria", []),
            contracts=d.get("contracts", ""),
            decisions=d.get("decisions", ""),
            consumer_notes=d.get("consumer_notes", ""),
            known_risks=d.get("known_risks", ""),
            validation_result=d.get("validation_result", {"passed": True}),
            handoff_bytes=d.get("handoff_bytes", 0),
            handoff_hash=stored_hash,
            created_at=d.get("created_at", ""),
            compacted=bool(d.get("compacted", False)),
            original_handoff_hash=d.get("original_handoff_hash", ""),
            synthesis_source=d.get("synthesis_source", "REAL"),
            contracts_truncated_to_string=bool(d.get("contracts_truncated_to_string", False)),
        )
        # Verify semantic bounds on loaded packet to prevent unconstrained reload injection
        actual_bytes = len(canonical_json_dump(hp.to_dict()).encode("utf-8"))
        if actual_bytes > MAX_SEMANTIC_HANDOFF_BYTES or hp.handoff_bytes > MAX_SEMANTIC_HANDOFF_BYTES:
            raise MalformedContextPacketError(
                f"Handoff packet {hp.handoff_id} payload exceeds maximum semantic bound: {max(actual_bytes, hp.handoff_bytes)} > {MAX_SEMANTIC_HANDOFF_BYTES}"
            )
        for field_name, field_val in [
            ("consumer_notes", hp.consumer_notes),
            ("contracts", hp.contracts),
            ("decisions", hp.decisions),
            ("known_risks", hp.known_risks),
        ]:
            if isinstance(field_val, str) and len(field_val.encode("utf-8")) > MAX_SEMANTIC_HANDOFF_BYTES:
                raise MalformedContextPacketError(
                    f"Handoff packet {hp.handoff_id} field '{field_name}' exceeds maximum semantic bound: {len(field_val.encode('utf-8'))} > {MAX_SEMANTIC_HANDOFF_BYTES}"
                )
        return hp

    def render_markdown(self) -> str:
        """Renders concise markdown representation for worker context."""
        lines = [
            f"#### Predecessor Handoff: `{self.producer_task_id}` (Commit `{self.commit or 'HEAD'}`)",
            f"- **Changed Paths**: {', '.join(f'`{p}`' for p in self.changed_paths) if self.changed_paths else 'None'}",
            f"- **Satisfied Criteria**: {', '.join(f'`{c}`' for c in self.satisfied_criteria) if self.satisfied_criteria else 'None'}",
        ]
        if self.contracts:
            c_text = self.contracts if isinstance(self.contracts, str) else json.dumps(self.contracts, indent=2)
            lines.append(f"- **Contracts / Interfaces**:\n```\n{c_text.strip()}\n```")
        if self.decisions:
            d_text = self.decisions if isinstance(self.decisions, str) else "\n".join(f"- {x}" for x in self.decisions)
            lines.append(f"- **Key Decisions**: {d_text}")
        if self.consumer_notes:
            lines.append(f"- **Consumer Notes**: {self.consumer_notes.strip()}")
        if self.known_risks:
            r_text = self.known_risks if isinstance(self.known_risks, str) else "\n".join(f"- {x}" for x in self.known_risks)
            lines.append(f"- **Known Risks**: {r_text}")
        return redact_secrets("\n".join(lines))


# ==============================================================================
# 3. CONTEXT SOURCE BOUNDARY
# ==============================================================================

class ContextSource:
    """Abstract interface defining the boundary for project context retrieval."""

    def get_file_hash(self, rel_path: str) -> str:
        raise NotImplementedError

    def get_file_bytes(self, rel_path: str) -> int:
        raise NotImplementedError

    def read_file_excerpt(self, rel_path: str, max_bytes: int = DEFAULT_MAX_INLINE_BYTES) -> Tuple[str, bool, str]:
        """Returns (excerpt_text, is_truncated, sha256_hash)."""
        raise NotImplementedError

    def get_bounded_file_inventory(self, max_files: int = 150, max_depth: int = 4) -> List[str]:
        raise NotImplementedError

    def get_git_diff(self, base_commit: str, target_commit: Optional[str] = None, max_bytes: int = 8192) -> Tuple[str, bool]:
        raise NotImplementedError

    def get_git_commit(self, ref: str = "HEAD") -> str:
        raise NotImplementedError


class FilesystemGitContextSource(ContextSource):
    """Default deterministic context source reading directly from the project Git repository."""

    SENSITIVE_PATTERNS = [
        re.compile(r"(^|/)\.env(\..*)?$", re.IGNORECASE),
        re.compile(r"(^|/)(?:secrets?\.)?env(?:\..*)?$", re.IGNORECASE),
        re.compile(r".*\.env$", re.IGNORECASE),
        re.compile(r"(^|/)\.envrc$", re.IGNORECASE),
        re.compile(r".*\.(pem|key|secret)$", re.IGNORECASE),
        re.compile(r"(^|/)\.aws(/|$)", re.IGNORECASE),
        re.compile(r"(^|/)\.ssh(/|$)", re.IGNORECASE),
        re.compile(r".*id_rsa.*", re.IGNORECASE),
        re.compile(r".*secrets?.*\.(ya?ml|json|cfg|ini|txt|conf|bak)$", re.IGNORECASE),
        re.compile(r".*credentials?.*\.(ya?ml|json|cfg|ini|txt|conf|bak)$", re.IGNORECASE),
        re.compile(r".*serviceAccount.*\.json$", re.IGNORECASE),
        re.compile(r"(^|/)\.netrc$", re.IGNORECASE),
    ]

    VALID_REF_PATTERN = re.compile(r"^[a-zA-Z0-9_./~^@{}-]{1,100}$")

    def __init__(self, project_root: pathlib.Path):
        self.project_root = project_root.resolve()

    def _is_sensitive_path(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/")
        return any(pat.search(norm) for pat in self.SENSITIVE_PATTERNS)

    def _resolve_safe_path(self, rel_path: str) -> pathlib.Path:
        if self._is_sensitive_path(rel_path):
            raise ContextError(f"Access to sensitive file path '{rel_path}' is forbidden")
        raw_path = self.project_root / rel_path
        if raw_path.is_symlink():
            raise ContextError(f"Symlinked file '{rel_path}' cannot be accessed directly by ContextSource")
        try:
            target = raw_path.resolve()
            target.relative_to(self.project_root)
        except (ValueError, RuntimeError):
            raise ContextError(f"Path traversal detected: {rel_path} escapes project root {self.project_root}")
        if os.path.realpath(str(raw_path)) != str(target):
            raise ContextError(f"Symlinked file '{rel_path}' cannot be accessed directly by ContextSource")
        return target

    def get_file_hash(self, rel_path: str) -> str:
        path = self._resolve_safe_path(rel_path)
        if path.is_symlink():
            raise ContextError(f"Symlinked file '{rel_path}' cannot be accessed directly by ContextSource")
        if not path.exists() or not path.is_file():
            return "MISSING"
        try:
            return sha256_bytes(path.read_bytes())
        except Exception:
            return "UNREADABLE"

    def get_file_bytes(self, rel_path: str) -> int:
        path = self._resolve_safe_path(rel_path)
        if path.is_symlink():
            raise ContextError(f"Symlinked file '{rel_path}' cannot be accessed directly by ContextSource")
        if not path.exists() or not path.is_file():
            return 0
        try:
            return path.stat().st_size
        except Exception:
            return 0

    def read_file_excerpt(self, rel_path: str, max_bytes: int = DEFAULT_MAX_INLINE_BYTES) -> Tuple[str, bool, str]:
        path = self._resolve_safe_path(rel_path)
        if path.is_symlink():
            raise ContextError(f"Symlinked file '{rel_path}' cannot be accessed directly by ContextSource")
        if not path.exists() or not path.is_file():
            return "", False, "MISSING"

        # Check for binary file
        data = path.read_bytes()
        full_hash = sha256_bytes(data)
        if b"\x00" in data[:1024]:
            return f"[BINARY FILE: {len(data)} bytes - inspect via tools]", False, full_hash

        truncated = len(data) > max_bytes
        excerpt_data = data[:max_bytes]
        text = excerpt_data.decode("utf-8", errors="replace")

        # Post-read content scan for sensitive token patterns
        text = redact_secrets(text)

        return text, truncated, full_hash

    def get_bounded_file_inventory(self, max_files: int = 150, max_depth: int = 4) -> List[str]:
        """Scans project repository deterministically, respecting boundaries and ignoring noisy directories.

        Defense-in-depth ordering:
        1. Dotfile & directory exclusion (primary guard): excludes hidden dirs/files (.git, .env, .aws, etc.).
        2. _is_sensitive_path (secondary defense): excludes non-dotfile sensitive files (secrets.json, id_rsa, *.pem, etc.).
        """
        ignore_dirs = {".git", ".agy-factory", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".eggs"}
        found = []

        try:
            for root, dirs, files in os.walk(self.project_root):
                # Filter ignore dirs and symlinked directories in-place
                rel_root = pathlib.Path(root).relative_to(self.project_root)
                dirs[:] = [
                    d for d in sorted(dirs)
                    if d not in ignore_dirs
                    and not d.startswith(".")
                    and not (pathlib.Path(root) / d).is_symlink()
                    and not self._is_sensitive_path(str((rel_root / d).as_posix()) + "/")
                ]
                depth = len(rel_root.parts)
                if depth > max_depth:
                    dirs[:] = []
                    continue

                for f in sorted(files):
                    full_f = pathlib.Path(root) / f
                    if full_f.is_symlink():
                        continue
                    if f.startswith("."):
                        continue
                    if f.endswith((".pyc", ".pyo", ".so", ".bin", ".tar", ".gz", ".zip")):
                        continue

                    rel_file = str(rel_root / f) if rel_root.parts else f
                    if self._is_sensitive_path(rel_file):
                        continue
                    found.append(rel_file)
                    if len(found) >= max_files:
                        return sorted(found)
        except (OSError, PermissionError) as e:
            raise ContextError(f"Failed to scan file inventory in {self.project_root}: {e}")

        return sorted(found)

    def get_git_commit(self, ref: str = "HEAD") -> str:
        if not self.VALID_REF_PATTERN.match(ref) or ref.startswith("-") or ".." in ref:
            return "UNKNOWN"
        try:
            proc = subprocess.run(
                ["git", "rev-parse", ref],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                val = proc.stdout.strip()
                if re.match(r"^[a-f0-9]{40}$", val):
                    return val
        except Exception:
            pass
        return "UNKNOWN"

    def get_git_diff(self, base_commit: str, target_commit: Optional[str] = None, max_bytes: int = 8192) -> Tuple[str, bool]:
        target = target_commit or "HEAD"
        # Resolve both refs to canonical 40-character SHA commits
        base_sha = self.get_git_commit(base_commit)
        target_sha = self.get_git_commit(target)
        if base_sha == "UNKNOWN" or not re.match(r"^[a-f0-9]{40}$", base_sha):
            raise ContextError(f"Invalid git base_commit ref: '{base_commit}'")
        if target_sha == "UNKNOWN" or not re.match(r"^[a-f0-9]{40}$", target_sha):
            raise ContextError(f"Invalid git target_commit ref: '{target}'")
        if base_sha == target_sha:
            return "", False

        cmd = ["git", "diff", base_sha, target_sha, "--"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                raw_diff = redact_secrets(proc.stdout)
                # Screen diff hunks for sensitive file paths
                filtered_lines = []
                skipping_sensitive = False
                redacted_count = 0
                for line in raw_diff.splitlines(keepends=True):
                    if line.startswith("diff --git "):
                        parts = line.split()
                        file_a = parts[2].removeprefix("a/") if len(parts) >= 3 else ""
                        file_b = parts[-1].removeprefix("b/") if len(parts) >= 4 else ""
                        skipping_sensitive = bool((file_a and self._is_sensitive_path(file_a)) or (file_b and self._is_sensitive_path(file_b)))
                        if skipping_sensitive:
                            redacted_count += 1
                            continue
                    elif line.startswith("--- ") or line.startswith("+++ "):
                        fn = line[4:].strip().split("\t")[0]
                        fn = fn.removeprefix("a/").removeprefix("b/")
                        if fn and self._is_sensitive_path(fn):
                            skipping_sensitive = True
                    if not skipping_sensitive:
                        filtered_lines.append(line)
                if redacted_count > 0:
                    filtered_lines.insert(0, f"[{redacted_count} SENSITIVE FILE(S) REDACTED]\n")
                clean_diff = "".join(filtered_lines)
                encoded = clean_diff.encode("utf-8")
                if len(encoded) > max_bytes:
                    truncated_text = encoded[:max_bytes - 64].decode("utf-8", errors="ignore")
                    return truncated_text + "\n\n... [DIFF TRUNCATED TO BUDGET] ...\n", True
                return clean_diff, False
        except Exception:
            pass
        return "", False


# ==============================================================================
# 4. CONTEXT POLICY & BUDGETS
# ==============================================================================

DEFAULT_CONTEXT_POLICY = {
    "$schema": "./schemas/context-policy.schema.json",
    "schema_version": "8.0.0",
    "description": "Default Factory v8.0.0 context policy",
    "default_session_mode": "fresh",
    "same_attempt_resume": True,
    "same_task_retry_mode": "fresh_with_attempt_handoff",
    "stable_prefix": {
        "version": STABLE_PREFIX_VERSION,
        "enforce_canonical_ordering": True,
    },
    "native_compaction_policy": {
        "agy": "disabled_by_default_fresh_session",
        "droid": "disabled_by_default_fresh_session",
        "codex": "disabled_by_default_fresh_session",
        "claude": "disabled_by_default_fresh_session",
        "opencode": "disabled_by_default_fresh_session",
    },
    "roles": {
        "planner": {
            "soft_budget_bytes": 8192,
            "hard_budget_bytes": 20480,
            "session_mode": "fresh",
            "max_handoff_bytes": 4096,
            "allow_zero_required_anchors": False,
        },
        "reviewer": {
            "soft_budget_bytes": 8192,
            "hard_budget_bytes": 20480,
            "session_mode": "fresh",
            "max_handoff_bytes": 4096,
            "allow_zero_required_anchors": False,
        },
        "task": {
            "soft_budget_bytes": 4096,
            "hard_budget_bytes": 12288,
            "session_mode": "fresh",
            "max_handoff_bytes": 4096,
            "allow_zero_required_anchors": False,
        },
        "auditor": {
            "soft_budget_bytes": 10240,
            "hard_budget_bytes": 24576,
            "session_mode": "fresh",
            "max_handoff_bytes": 4096,
            "allow_zero_required_anchors": False,
        },
        "remediation": {
            "soft_budget_bytes": 6144,
            "hard_budget_bytes": 16384,
            "session_mode": "fresh",
            "max_handoff_bytes": 4096,
            "allow_zero_required_anchors": False,
        },
    },
}


class ContextPolicy:
    """Manages role-specific context budgets, session modes, and pruning constraints."""

    def __init__(self, data: dict, project_overrides: Optional[dict] = None):
        self.raw = copy.deepcopy(data)
        self.schema_version = self.raw.get("schema_version", "8.0.0")
        self.default_session_mode = self.raw.get("default_session_mode", "fresh")
        self.same_attempt_resume = self.raw.get("same_attempt_resume", True)
        self.same_task_retry_mode = self.raw.get("same_task_retry_mode", "fresh_with_attempt_handoff")
        self.roles = copy.deepcopy(self.raw.get("roles", {}))
        self.validate()

        # Apply project overrides safely
        if project_overrides:
            self.apply_project_overrides(project_overrides)

    def validate(self) -> None:
        """Validates policy against architectural invariants."""
        if self.default_session_mode not in ("fresh", "resume"):
            raise ContextError(f"Invalid default_session_mode: {self.default_session_mode}")

        valid_roles = {"planner", "reviewer", "task", "auditor", "remediation"}
        for role, rdata in self.roles.items():
            if role not in valid_roles:
                raise ContextError(f"Unknown role '{role}' in context policy")
            soft = rdata.get("soft_budget_bytes", 0)
            hard = rdata.get("hard_budget_bytes", 0)
            if soft <= 0:
                raise ContextError(f"Role '{role}' soft_budget_bytes must be > 0 (got {soft})")
            if hard < soft:
                raise ContextError(f"Role '{role}' hard_budget_bytes ({hard}) cannot be less than soft ({soft})")
            if rdata.get("session_mode") not in ("fresh", "resume"):
                raise ContextError(f"Role '{role}' session_mode must be 'fresh' or 'resume'")
            if rdata.get("allow_zero_required_anchors", False) is True:
                raise ContextError(f"Role '{role}' allow_zero_required_anchors cannot be True")

    def apply_project_overrides(self, overrides: dict) -> None:
        """Applies project context overrides. Only allows narrowing budgets, never weakening gates."""
        if not isinstance(overrides, dict):
            return

        # Explicitly block tampering with global policy fields
        disallowed_globals = {"default_session_mode", "same_attempt_resume", "same_task_retry_mode", "schema_version"}
        for k in overrides:
            if k in disallowed_globals:
                raise ContextError(f"Project overrides cannot alter global field '{k}'")

        role_overrides = overrides.get("roles", {})
        for role, odata in role_overrides.items():
            if not isinstance(odata, dict):
                continue
            # Block any role fields other than budget narrowing
            for rk in odata:
                if rk not in ("soft_budget_bytes", "hard_budget_bytes"):
                    raise ContextError(f"Project override for role '{role}' cannot modify field '{rk}'")
            for b_field in ("soft_budget_bytes", "hard_budget_bytes"):
                if b_field in odata:
                    val = odata[b_field]
                    if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                        raise ContextError(
                            f"Project override for role '{role}' field '{b_field}' must be a positive integer, got: {repr(val)}"
                        )
            if role in self.roles:
                cur = self.roles[role]
                new_soft = cur["soft_budget_bytes"]
                new_hard = cur["hard_budget_bytes"]
                # Can only narrow (lower) budgets
                if "soft_budget_bytes" in odata:
                    new_soft = min(cur["soft_budget_bytes"], odata["soft_budget_bytes"])
                if "hard_budget_bytes" in odata:
                    new_hard = min(cur["hard_budget_bytes"], odata["hard_budget_bytes"])
                if new_hard < new_soft:
                    raise ContextError(
                        f"Override for role '{role}' results in hard_budget_bytes ({new_hard}) < soft_budget_bytes ({new_soft})"
                    )
                cur["soft_budget_bytes"] = new_soft
                cur["hard_budget_bytes"] = new_hard

        self.validate()

    def get_role_policy(self, role: str) -> dict:
        if role not in self.roles:
            raise ContextError(f"Unknown context policy role: '{role}'. Must be one of {sorted(self.roles.keys())}")
        return self.roles[role]

    @classmethod
    def load(cls, path: Optional[pathlib.Path] = None, project_overrides: Optional[dict] = None) -> ContextPolicy:
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(data, project_overrides=project_overrides)
            except Exception as e:
                raise ContextError(f"Failed to load context policy from {path}: {e}")
        return cls(DEFAULT_CONTEXT_POLICY, project_overrides=project_overrides)


# ==============================================================================
# 5. STABLE PREFIX ARCHITECTURE
# ==============================================================================

class StablePrefixManager:
    """Manages role-specific deterministic stable prefixes."""

    _WORKER_PREFIX = """# Factory Worker Operational Contract
You are an automated software engineering worker executing in an isolated Git worktree.

## Strict Operational Guardrails
1. Assigned Workspace: Operate exclusively within your assigned worktree directory.
2. Allowed Paths: Only modify paths matching the allowed patterns declared in your dynamic packet.
3. No Package Installation: DO NOT install external packages via pip, npm, apt, or any package manager.
4. No Environment Mutation: DO NOT alter .venv, .agy-factory, or host configurations.
5. No Version Control Manipulation: DO NOT run git commit/push/branch/merge. Git lifecycle is owned by Factory.
6. Tool Usage: Use write_to_file and replace_file_content. DO NOT execute arbitrary shell commands.
7. Direct Implementation: DO NOT invoke subagents. Complete all implementation directly in this session.

## Worker Output Schema
Return a valid JSON object matching the worker result schema:
```json
{
  "task_id": "<task_id>",
  "status": "COMPLETED" | "FAILED",
  "summary": "<clear summary of what was implemented>",
  "changed_files": ["<list of relative paths created or modified>"],
  "notes": "<optional design notes or considerations>"
}
```
"""

    _REVIEWER_PREFIX = """# Project Autopilot Independent Plan Reviewer Contract
You are the Independent Plan Reviewer evaluating an orchestration DAG plan against a Goal Specification.

## Review Invariants
1. Completeness: Ensure all acceptance criteria are covered by task satisfies mappings.
2. Scope Bounds: Flag unnecessary over-engineering, orphan tasks, or scope creep.
3. Deterministic Validation: Ensure all tasks specify executable, deterministic validation commands.
4. Path Boundaries: Ensure tasks declare explicit allowed_paths conforming to project policy.

## Review Output Schema
Output ONLY a JSON object conforming to the review schema:
```json
{
  "verdict": "APPROVED" | "REVISE" | "BLOCKED",
  "revision_index": <int>,
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "traceability" | "scope" | "verification" | "security",
      "description": "<finding description>",
      "suggested_action": "<concrete action to resolve>"
    }
  ]
}
```
"""

    _AUDITOR_PREFIX = """# Project Autopilot Independent Final Auditor Contract
You are the Independent Final Auditor evaluating target codebase implementation against the Goal Specification.

## Audit Invariants
1. Verification: Inspect validation evidence, git diff, and criteria traceability.
2. Codebase Inspection: Read target source files directly from the repository on disk.
3. Determinism: Validate that no external unvetted dependencies were introduced.
4. Strict Verdict: Return ACCEPTED only if all criteria are satisfied and all deterministic tests pass.

## Auditor Output Schema
Output ONLY a JSON object conforming to the audit schema:
```json
{
  "verdict": "ACCEPTED" | "REMEDIATION_REQUIRED",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "area": "implementation" | "tests" | "security" | "traceability",
      "evidence": "<concrete evidence or file reference>",
      "recommendation": "<suggested remediation>"
    }
  ]
}
```
"""

    _PLANNER_PREFIX = """# Project Autopilot Plan Compiler Contract
You are the Plan Compiler structuring high-level goals into an executable DAG orchestration plan.

## Planning Invariants
1. Full Traceability: Every criterion must be mapped to at least one task's satisfies array.
2. Acyclic DAG: Dependencies must form a strict directed acyclic graph.
3. Isolated Boundaries: Tasks must define explicit allowed_paths and deterministic validation commands.
4. stdlib Only: Adhere strictly to the target project language standard library unless policy permits.
"""

    _REMEDIATION_PREFIX = """# Factory Remediation Worker Contract
You are an automated software engineering remediation worker resolving defects identified during audit.

## Strict Operational Guardrails
1. Minimal Scope: Focus strictly on repairing the identified audit findings and failing validations.
2. Assigned Workspace: Operate exclusively within your assigned worktree directory.
3. Allowed Paths: Only modify paths matching the declared allowed patterns.
4. No Package Installation: DO NOT install external packages via pip, npm, apt, or any package manager.
5. Verification: Verify all fixes against the provided validation commands before completing.

## Remediation Output Schema
Return a valid JSON object matching the worker result schema:
```json
{
  "task_id": "<task_id>",
  "status": "COMPLETED" | "FAILED",
  "summary": "<clear summary of fixes implemented>",
  "changed_files": ["<list of relative paths modified>"],
  "notes": "<remediation notes>"
}
```
"""

    @classmethod
    def get_stable_prefix(cls, role: str) -> Tuple[str, str, int]:
        """Returns (prefix_text, prefix_hash, prefix_bytes) for the given role."""
        if role in ("worker", "task"):
            text = cls._WORKER_PREFIX
        elif role in ("reviewer", "plan_reviewer"):
            text = cls._REVIEWER_PREFIX
        elif role in ("auditor", "final_auditor"):
            text = cls._AUDITOR_PREFIX
        elif role == "planner":
            text = cls._PLANNER_PREFIX
        elif role in ("remediation", "remediation_worker"):
            text = cls._REMEDIATION_PREFIX
        else:
            raise ContextError(f"Unknown or unsupported role '{role}' for stable prefix")

        # Canonical normalization
        normalized = text.strip() + "\n"
        encoded = normalized.encode("utf-8")
        h = sha256_bytes(encoded)
        return normalized, h, len(encoded)


# ==============================================================================
# 6. CONTEXT REDUNDANCY CALCULATOR
# ==============================================================================

def calculate_context_redundancy(texts: List[str], chunk_size: int = 64) -> Dict[str, Any]:
    """Calculates deterministic chunk-level redundancy across a collection of text prompts.

    Uses bounded content-addressed line/chunk segmentation.
    Redundancy ratio is defined as repeated_bytes / total_bytes where repeated_bytes counts
    all occurrences of chunks appearing more than once across the collection.
    Returns:
        total_factory_supplied_bytes, unique_content_bytes, repeated_content_bytes, redundancy_ratio
    """
    all_chunks = []
    chunk_counts: Dict[str, int] = {}
    chunk_lengths: Dict[str, int] = {}

    for t in texts:
        lines = [l + "\n" for l in t.splitlines()]
        for line in lines:
            line_bytes = line.encode("utf-8")
            lb_len = len(line_bytes)

            # For fine-grained accounting, chunk lines if large
            if lb_len > chunk_size:
                for i in range(0, lb_len, chunk_size):
                    sub = line_bytes[i:i + chunk_size]
                    h = sha256_bytes(sub)
                    chunk_counts[h] = chunk_counts.get(h, 0) + 1
                    chunk_lengths[h] = len(sub)
                    all_chunks.append(h)
            else:
                h = sha256_bytes(line_bytes)
                chunk_counts[h] = chunk_counts.get(h, 0) + 1
                chunk_lengths[h] = lb_len
                all_chunks.append(h)

    total_bytes = sum(chunk_lengths[h] for h in all_chunks)
    repeated_bytes = sum(chunk_lengths[h] for h in all_chunks if chunk_counts[h] > 1)
    unique_bytes = sum(chunk_lengths[h] for h in all_chunks if chunk_counts[h] == 1)

    ratio = (repeated_bytes / total_bytes) if total_bytes > 0 else 0.0
    return {
        "total_factory_supplied_bytes": total_bytes,
        "run_total_context_bytes": total_bytes,
        "unique_content_bytes": unique_bytes,
        "repeated_content_bytes": repeated_bytes,
        "redundancy_ratio": round(ratio, 4),
    }


# ==============================================================================
# 7. CONTEXT PACKET DATA MODEL
# ==============================================================================

@dataclasses.dataclass
class ContextPacket:
    """Canonical, bounded, immutable context packet prepared for a specific agent execution."""
    schema_version: str
    packet_id: str
    packet_role: str
    goal_id: str
    source_artifacts: List[str]
    source_hashes: Dict[str, str]
    requirements: List[dict]
    required_anchors: List[Anchor]
    included_files: List[dict]
    referenced_files: List[str]
    validations: List[List[str]]
    budget: dict
    packet_bytes: int
    packet_hash: str
    compiler_version: str
    created_at: str
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_id: Optional[int] = None
    dependencies: List[str] = dataclasses.field(default_factory=list)
    handoffs: List[dict] = dataclasses.field(default_factory=list)
    constraints: List[str] = dataclasses.field(default_factory=list)
    rendered_tail: str = ""
    token_count: Optional[int] = None
    token_count_source: Optional[str] = None
    metadata_hash: Optional[str] = None

    @staticmethod
    def compute_metadata_hash(packet_id: str, packet_bytes: int, token_count: Optional[int], token_count_source: Optional[str], budget: dict) -> str:
        meta = {
            "packet_id": str(packet_id),
            "packet_bytes": int(packet_bytes),
            "token_count": token_count,
            "token_count_source": token_count_source,
            "budget": budget or {},
        }
        return sha256_text(canonical_json_dump(meta))

    def calculate_metadata_hash(self) -> str:
        return self.compute_metadata_hash(self.packet_id, self.packet_bytes, self.token_count, self.token_count_source, self.budget)

    def calculate_required_anchor_recall(self) -> Tuple[float, List[str]]:
        rendered = self.render_full_prompt()
        return calculate_rendered_anchor_recall(self.required_anchors, rendered)

    def render_full_prompt(self) -> str:
        """Returns the full rendered prompt combining the stable prefix and rendered tail, secret-redacted."""
        if not self.rendered_tail:
            raise ContextError(f"ContextPacket {self.packet_id} has empty rendered_tail; cannot render full prompt")
        stable_prefix, _, _ = StablePrefixManager.get_stable_prefix(self.packet_role)
        return redact_secrets(stable_prefix + "\n" + self.rendered_tail)

    def verify_staleness(self, current_source_hashes: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Checks if any source artifact has changed since packet compilation."""
        stale_reasons = []
        for path, orig_hash in self.source_hashes.items():
            curr = current_source_hashes.get(path)
            if curr != orig_hash:
                stale_reasons.append(f"{path} changed ({orig_hash[:8]} -> {curr[:8] if curr else 'MISSING'})")
        for path, curr_hash in current_source_hashes.items():
            if path not in self.source_hashes:
                stale_reasons.append(f"expected source {path} missing in packet source_hashes")
        return len(stale_reasons) > 0, stale_reasons

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "packet_id": self.packet_id,
            "packet_role": self.packet_role,
            "goal_id": self.goal_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "source_artifacts": sorted(self.source_artifacts),
            "source_hashes": dict(sorted(self.source_hashes.items())),
            "requirements": self.requirements,
            "required_anchors": [a.to_dict() for a in self.required_anchors],
            "included_files": self.included_files,
            "referenced_files": sorted(self.referenced_files),
            "dependencies": sorted(self.dependencies),
            "handoffs": self.handoffs,
            "validations": self.validations,
            "constraints": sorted(self.constraints),
            "budget": self.budget,
            "packet_bytes": self.packet_bytes,
            "packet_hash": self.packet_hash,
            "metadata_hash": self.calculate_metadata_hash(),
            "token_count": self.token_count,
            "token_count_source": self.token_count_source,
            "compiler_version": self.compiler_version,
            "created_at": self.created_at,
            "rendered_tail": self.rendered_tail,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ContextPacket:
        stored_hash = d.get("packet_hash", "")
        if not stored_hash:
            raise MalformedContextPacketError(f"ContextPacket is missing required packet_hash field: {d.get('packet_id', 'unknown')}")
        role = d.get("packet_role", "")
        rendered_tail = d.get("rendered_tail", "")
        stable_prefix, _, _ = StablePrefixManager.get_stable_prefix(role)
        expected_prompt = redact_secrets(stable_prefix + "\n" + rendered_tail)
        computed_hash = sha256_text(expected_prompt)
        if computed_hash != stored_hash:
            orig_prefix_hash = d.get("source_hashes", {}).get("stable_prefix")
            current_prefix_hash = sha256_text(stable_prefix)
            if orig_prefix_hash and orig_prefix_hash != current_prefix_hash:
                raise MalformedContextPacketError(
                    f"ContextPacket {d.get('packet_id')} invalid due to stable prefix drift: compiled with {orig_prefix_hash[:8]}, current is {current_prefix_hash[:8]}"
                )
            stored_fp = d.get("source_hashes", {}).get("secret_env")
            current_fp = get_secret_env_fingerprint()
            if stored_fp and stored_fp != current_fp:
                raise StaleContextPacketError(
                    f"ContextPacket {d.get('packet_id')} invalid due to secret environment drift: compiled with fingerprint {stored_fp[:8]}, current is {current_fp[:8]}"
                )
            raise MalformedContextPacketError(
                f"ContextPacket structural corruption detected for {d.get('packet_id')}: stored hash {stored_hash[:8]} != computed hash {computed_hash[:8]}"
            )

        stored_meta_hash = d.get("metadata_hash")
        if stored_meta_hash:
            computed_meta_hash = cls.compute_metadata_hash(
                d.get("packet_id", ""),
                d.get("packet_bytes", 0),
                d.get("token_count"),
                d.get("token_count_source"),
                d.get("budget", {})
            )
            if computed_meta_hash != stored_meta_hash:
                raise MalformedContextPacketError(
                    f"ContextPacket metadata tampering detected for {d.get('packet_id')}: stored metadata hash {stored_meta_hash[:8]} != computed metadata hash {computed_meta_hash[:8]}"
                )

        if d.get("packet_bytes") is not None and d.get("packet_bytes") != len(expected_prompt.encode("utf-8")):
            raise MalformedContextPacketError(
                f"ContextPacket byte length mismatch for {d.get('packet_id')}: stored {d.get('packet_bytes')} != actual {len(expected_prompt.encode('utf-8'))}"
            )

        anchors = [Anchor.from_dict(a) for a in d.get("required_anchors", [])]
        role = d.get("packet_role", "")
        cls_map = {
            "planner": PlannerContextPacket,
            "reviewer": PlanReviewContextPacket,
            "task": TaskContextPacket,
            "auditor": AuditContextPacket,
            "remediation": RemediationContextPacket,
        }
        target_cls = cls_map.get(role, cls)
        return target_cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            packet_id=d["packet_id"],
            packet_role=d["packet_role"],
            goal_id=d["goal_id"],
            run_id=d.get("run_id"),
            task_id=d.get("task_id"),
            attempt_id=d.get("attempt_id"),
            source_artifacts=d.get("source_artifacts", []),
            source_hashes=d.get("source_hashes", {}),
            requirements=d.get("requirements", []),
            required_anchors=anchors,
            included_files=d.get("included_files", []),
            referenced_files=d.get("referenced_files", []),
            dependencies=d.get("dependencies", []),
            handoffs=d.get("handoffs", []),
            validations=d.get("validations", []),
            constraints=d.get("constraints", []),
            budget=d.get("budget", {}),
            packet_bytes=d.get("packet_bytes", 0),
            packet_hash=d.get("packet_hash", ""),
            metadata_hash=d.get("metadata_hash"),
            compiler_version=d.get("compiler_version", COMPILER_VERSION),
            created_at=d.get("created_at", ""),
            rendered_tail=d.get("rendered_tail", ""),
            token_count=d.get("token_count"),
            token_count_source=d.get("token_count_source"),
        )


class PlannerContextPacket(ContextPacket):
    """Immutable context packet compiled specifically for the Planner."""
    pass


class PlanReviewContextPacket(ContextPacket):
    """Immutable context packet compiled specifically for the Plan Reviewer."""
    pass


class TaskContextPacket(ContextPacket):
    """Immutable context packet compiled specifically for Task Workers."""
    pass


class AuditContextPacket(ContextPacket):
    """Immutable context packet compiled specifically for the Final Auditor."""
    pass


class RemediationContextPacket(ContextPacket):
    """Immutable context packet compiled specifically for Remediation Workers."""
    pass


# ==============================================================================
# 8. CONTEXT COMPILER
# ==============================================================================

class ContextCompiler:
    """First-class compiler producing bounded, immutable, role-specific context packets."""

    def __init__(self, context_policy: ContextPolicy, context_source: ContextSource):
        self.policy = context_policy
        self.source = context_source

    def _render_task_dynamic_tail(
        self,
        task_id: str,
        attempt_id: int,
        worktree_path: str,
        allowed_paths: List[str],
        requirements: List[dict],
        referenced_files: List[str],
        included_files: List[dict],
        handoffs: List[HandoffPacket],
        validations: List[List[str]],
        task_prompt: str,
        retry_info: Optional[dict] = None,
    ) -> str:
        """Renders dynamic tail markdown for worker task."""
        sections = []

        # 1. Assignment Header
        sections.append(f"## Active Task Assignment: `{task_id}` (Attempt #{attempt_id})")
        sections.append(f"- **Assigned Worktree Root**: `{worktree_path}`")
        sections.append(f"- **Allowed Path Patterns**: {', '.join(f'`{p}`' for p in allowed_paths)}")

        # 2. Requirements to Satisfy (Scoped to this task)
        if requirements:
            req_lines = ["\n### Acceptance Criteria to Satisfy:"]
            for r in requirements:
                cid = r.get("id", "R")
                desc = r.get("description", "")
                title = r.get("title", cid)
                req_lines.append(f"- **{cid}** ({title}): {desc}")
            sections.append("\n".join(req_lines))

        # 3. Available Files on Disk (Referenced, not inlined)
        if referenced_files:
            file_lines = ["\n### Target Files Available on Disk (Inspect via Tools):"]
            for f in referenced_files:
                file_lines.append(f"- `{f}`")
            sections.append("\n".join(file_lines))

        # 4. Inlined Excerpts (Only if explicitly required)
        if included_files:
            inc_lines = ["\n### Inlined Context Excerpts:"]
            for inc in included_files:
                inc_lines.append(f"#### Excerpt: `{inc['path']}` (Reason: {inc['reason']})")
                inc_lines.append(f"```\n{inc['inline_content']}\n```")
            sections.append("\n".join(inc_lines))

        # 5. Predecessor Handoffs
        if handoffs:
            ho_lines = ["\n### Predecessor Task Handoffs:"]
            for h in handoffs:
                ho_lines.append(redact_secrets(h.render_markdown()))
            sections.append("\n".join(ho_lines))

        # 6. Retry Information (if previous attempt failed)
        if retry_info:
            prev_att = retry_info.get("previous_attempt_id", retry_info.get("attempt", 1))
            ret_lines = [
                f"\n### Previous Attempt Failure Guidance (Attempt #{prev_att}):",
                f"- **Failed Status**: {retry_info.get('status', 'FAILED')}",
                f"- **Error Category**: {retry_info.get('error_category', 'VALIDATION_FAILED')}",
            ]
            def _sanitize_err_text(val: Any, max_bytes: int = 2048) -> str:
                if not val:
                    return ""
                s = unicodedata.normalize("NFKC", str(val).strip())
                # Strip unicode format (Cf) and control (Cc) characters except \n, \r, \t
                s = "".join(c for c in s if (unicodedata.category(c) not in ('Cf', 'Cc') or c in ('\n', '\r', '\t')))
                s = redact_secrets(s)
                s = normalize_homoglyphs(unicodedata.normalize("NFKC", s))
                s = INJECTION_PATTERN.sub("[FILTERED]", s)
                encoded = s.encode("utf-8")[:max_bytes]
                return encoded.decode("utf-8", errors="ignore")

            if retry_info.get("failing_command"):
                cmd_val = retry_info["failing_command"]
                if isinstance(cmd_val, list):
                    cmd_str = shlex.join(str(x) for x in cmd_val)
                else:
                    cmd_str = str(cmd_val)
                ret_lines.append(f"- **Failing Command**: `{_sanitize_err_text(cmd_str)}`")
            err_text = retry_info.get("error_excerpt") or retry_info.get("error_summary") or retry_info.get("error")
            if err_text:
                ret_lines.append(f"- **Error Output**:\n```\n{_sanitize_err_text(err_text)}\n```")
            sections.append("\n".join(ret_lines))

        # 7. Deterministic Validation Commands
        if validations:
            val_lines = ["\n### Deterministic Validation Commands:"]
            for v in validations:
                val_lines.append(f"- `{' '.join(v)}`")
            sections.append("\n".join(val_lines))

        # 8. Specific Task Instructions
        if task_prompt:
            task_prompt_bounded = task_prompt.encode("utf-8")[:2048].decode("utf-8", errors="ignore")
            clean_prompt = redact_secrets(task_prompt_bounded.strip())
            sections.append(f"\n### Task Instructions\n{clean_prompt}")

        return redact_secrets("\n\n".join(sections) + "\n")

    def compile_task_packet(
        self,
        goal_id: str,
        run_id: str,
        task_id: str,
        attempt_id: int,
        task_def: dict,
        plan: dict,
        goal_spec: dict,
        worktree_path: str,
        allowed_paths: List[str],
        dependencies: List[str],
        handoffs: List[HandoffPacket],
        retry_info: Optional[dict] = None,
        extra_referenced_files: Optional[List[str]] = None,
    ) -> ContextPacket:
        """Compiles a TaskContextPacket for worker dispatch, enforcing budget pruning and anchor gate."""
        role = "task"
        role_policy = self.policy.get_role_policy(role)
        soft_budget = role_policy["soft_budget_bytes"]
        hard_budget = role_policy["hard_budget_bytes"]

        stable_prefix, prefix_hash, _ = StablePrefixManager.get_stable_prefix(role)

        # Track sources and hashes
        source_artifacts = ["goal-spec.json", "plan.json"]
        source_hashes = {
            "goal-spec": sha256_text(canonical_json_dump(goal_spec)),
            "plan": sha256_text(canonical_json_dump(plan)),
            "task_def": sha256_text(canonical_json_dump(task_def)),
            "retry_info": sha256_text(canonical_json_dump(retry_info or {})),
            "stable_prefix": prefix_hash,
            "secret_env": get_secret_env_fingerprint(),
        }

        # Build scoped acceptance criteria
        criteria_map = {c["id"]: c for c in goal_spec.get("acceptance_criteria", [])}
        satisfies_ids = task_def.get("satisfies", [])
        task_requirements = [criteria_map[cid] for cid in satisfies_ids if cid in criteria_map]
        for r in task_requirements:
            validate_criterion_provenance(r)

        # Build Anchors
        anchors: List[Anchor] = []
        for r in task_requirements:
            anchors.append(
                Anchor(
                    anchor_id=f"req:{r['id']}",
                    anchor_type="requirement",
                    source=f"goal_spec:{r['id']}",
                    source_hash=sha256_text(r["description"]),
                    content=r["description"],
                    required=True,
                )
            )

        for p in allowed_paths:
            anchors.append(
                Anchor(
                    anchor_id=f"path:{p}",
                    anchor_type="allowed_path",
                    source="task_def:allowed_paths",
                    source_hash=sha256_text(p),
                    content=p,
                    required=True,
                )
            )

        validations = task_def.get("validations", [])
        for v in validations:
            cmd_str = " ".join(v)
            anchors.append(
                Anchor(
                    anchor_id=f"val:{sha256_text(cmd_str)[:8]}",
                    anchor_type="validation",
                    source="task_def:validations",
                    source_hash=sha256_text(cmd_str),
                    content=cmd_str,
                    required=True,
                )
            )

        # File references (default over inlining)
        referenced_files: List[str] = []
        if (self.source.project_root / "GOAL.md").exists():
            referenced_files.append("GOAL.md")
        if (self.source.project_root / "README.md").exists():
            referenced_files.append("README.md")
        if extra_referenced_files:
            referenced_files.extend(extra_referenced_files)
            for ef in extra_referenced_files:
                anchors.append(
                    Anchor(
                        anchor_id=f"extra_ref:{sha256_text(ef)[:8]}",
                        anchor_type="file_reference",
                        source="extra_referenced_files",
                        source_hash=sha256_text(ef),
                        content=ef,
                        required=False,
                    )
                )
        for cf in task_def.get("context_files", []):
            if isinstance(cf, str) and cf not in referenced_files:
                referenced_files.append(cf)
            anchors.append(
                Anchor(
                    anchor_id=f"context_file:{sha256_text(cf)[:8]}",
                    anchor_type="file_reference",
                    source="task_def:context_files",
                    source_hash=sha256_text(cf),
                    content=cf,
                    required=False,
                )
            )
        # Add dependency changed paths and normalize handoffs
        norm_handoffs: List[HandoffPacket] = []
        handoff_required_paths: Set[str] = set()
        for ho in handoffs:
            if isinstance(ho, HandoffPacket):
                norm_handoffs.append(ho)
                valid_paths = [p for p in ho.changed_paths[:200] if not str(p).startswith("[+")]
                referenced_files.extend(valid_paths)
                handoff_required_paths.update(valid_paths)
            elif isinstance(ho, dict):
                hp = HandoffPacket(
                    handoff_id=ho.get("handoff_id", f"ho-{uuid.uuid4().hex[:8]}"),
                    producer_task_id=ho.get("producer_task_id", ho.get("from_task", "unknown")),
                    producer_attempt=ho.get("producer_attempt", ho.get("attempt", 1)),
                    changed_paths=ho.get("changed_paths", []),
                    satisfied_criteria=ho.get("satisfied_criteria", []),
                    commit=ho.get("commit"),
                    contracts=ho.get("contracts", ""),
                    decisions=ho.get("decisions", ""),
                    consumer_notes=ho.get("consumer_notes", ho.get("summary", "")),
                    known_risks=ho.get("known_risks", ""),
                    validation_result=ho.get("validation_result", {"passed": True}),
                    compacted=bool(ho.get("compacted", False)),
                    original_handoff_hash=ho.get("original_handoff_hash", ""),
                    synthesis_source=ho.get("synthesis_source", "REAL"),
                )
                norm_handoffs.append(hp)
                valid_paths = [p for p in hp.changed_paths[:200] if not str(p).startswith("[+")]
                referenced_files.extend(valid_paths)
                handoff_required_paths.update(valid_paths)
        handoffs = norm_handoffs

        # Register handoff changed paths as required anchors to prevent silent loss
        for ho_path in sorted(handoff_required_paths):
            anchors.append(
                Anchor(
                    anchor_id=f"handoff_path:{sha256_text(ho_path)[:8]}",
                    anchor_type="file_reference",
                    source="predecessor_handoff",
                    source_hash=sha256_text(ho_path),
                    content=ho_path,
                    required=True,
                )
            )

        referenced_files = sorted(set(referenced_files))

        # Check for inline files (none by default unless explicitly needed)
        included_files: List[dict] = []

        # Prepare initial dynamic tail (bound prompt to 2048 bytes and sanitize injection/homoglyphs)
        raw_tp = str(task_def.get("prompt", ""))
        raw_tp = unicodedata.normalize("NFKC", raw_tp)
        raw_tp = "".join(c for c in raw_tp if (unicodedata.category(c) not in ('Cf', 'Cc') or c in ('\n', '\r', '\t')))
        raw_tp = normalize_homoglyphs(raw_tp)
        raw_tp = INJECTION_PATTERN.sub("[FILTERED]", raw_tp)
        raw_tp = redact_secrets(raw_tp)
        task_prompt = raw_tp.encode("utf-8")[:2048].decode("utf-8", errors="ignore")
        tail = self._render_task_dynamic_tail(
            task_id, attempt_id, worktree_path, allowed_paths,
            task_requirements, referenced_files, included_files,
            handoffs, validations, task_prompt, retry_info=retry_info
        )

        original_bytes = len(tail.encode("utf-8"))
        pruned = False
        dropped_files: List[str] = []

        # Pruning loop if above soft budget
        current_tail = tail
        current_bytes = original_bytes

        if current_bytes > soft_budget:
            pruned = True
            # Step 1: Remove duplicate/excess file references using strict path matching
            # Preserving all handoff_required_paths without truncating them
            def _is_path_allowed(fpath: str) -> bool:
                if fpath in handoff_required_paths:
                    return True
                try:
                    p_file = pathlib.PurePosixPath(fpath)
                    for pat in allowed_paths:
                        p_pat = pathlib.PurePosixPath(pat)
                        if p_file == p_pat or p_pat in p_file.parents or fnmatch.fnmatch(fpath, pat):
                            return True
                except Exception:
                    pass
                return False

            task_context_files = set(task_def.get("context_files", []))
            core_files = sorted(set(list(handoff_required_paths) + [f for f in task_context_files if _is_path_allowed(f) and (self.source.project_root / f).exists()] + [f for f in {"GOAL.md", "README.md"} if (self.source.project_root / f).exists()]))
            extra_files = [f for f in referenced_files if f not in core_files]
            filtered_extra = [f for f in extra_files if _is_path_allowed(f)][:10]
            dropped_files = [f for f in extra_files if f not in core_files and f not in filtered_extra]
            referenced_files = sorted(set(core_files + filtered_extra))

            # Step 2: Bound handoff notes while preserving original handoff hash for traceability
            compact_handoffs = []
            for ho in handoffs:
                orig_hash = ho.original_handoff_hash or ho.handoff_hash
                if not orig_hash or len(orig_hash) not in (40, 64) or not re.match(r"^[0-9a-fA-F]+$", orig_hash):
                    raise MalformedContextPacketError(f"Handoff {ho.handoff_id} has invalid pre-compaction hash '{orig_hash}'")
                h_copy = copy.deepcopy(ho)
                h_copy.compacted = True
                h_copy.original_handoff_hash = orig_hash
                h_copy.handoff_hash = ""
                # Re-run sanitization on free text fields before bounding & hash recomputation
                if isinstance(h_copy.consumer_notes, str):
                    h_copy.consumer_notes = redact_secrets(INJECTION_PATTERN.sub("[FILTERED]", h_copy.consumer_notes))
                if isinstance(h_copy.decisions, str):
                    h_copy.decisions = redact_secrets(INJECTION_PATTERN.sub("[FILTERED]", h_copy.decisions))
                elif isinstance(h_copy.decisions, list):
                    h_copy.decisions = [redact_secrets(INJECTION_PATTERN.sub("[FILTERED]", str(x))) for x in h_copy.decisions]
                if isinstance(h_copy.known_risks, str):
                    h_copy.known_risks = redact_secrets(INJECTION_PATTERN.sub("[FILTERED]", h_copy.known_risks))
                elif isinstance(h_copy.known_risks, list):
                    h_copy.known_risks = [redact_secrets(INJECTION_PATTERN.sub("[FILTERED]", str(x))) for x in h_copy.known_risks]
                if isinstance(h_copy.contracts, str):
                    h_copy.contracts = redact_secrets(INJECTION_PATTERN.sub("[FILTERED]", h_copy.contracts))
                h_copy.enforce_semantic_bounds(max_bytes=1024)
                compact_handoffs.append(h_copy)
            handoffs = compact_handoffs

            # Re-synchronize surviving handoff path anchors after compaction to prevent false anchor recall misses
            surviving_paths = set()
            # Top-5 changed paths from each predecessor handoff are guaranteed hard anchors
            guaranteed_paths = set()
            for ho in handoffs:
                valid_paths = [p for p in ho.changed_paths if not str(p).startswith("[+")]
                guaranteed_paths.update(valid_paths[:5])
                surviving_paths.update(valid_paths[:200])
            surviving_paths.update(guaranteed_paths)

            demoted_paths = []
            for a in anchors:
                if a.anchor_type == "file_reference" and a.source == "predecessor_handoff":
                    if a.content in guaranteed_paths:
                        a.required = True
                    elif a.content not in surviving_paths:
                        a.required = False
                        demoted_paths.append(a.content)
            if demoted_paths:
                logging.getLogger("factory").warning("WARNING_HANDOFF_PATH_ANCHOR_DEMOTED: Demoted %d predecessor handoff paths under budget pressure: %s", len(demoted_paths), demoted_paths)
            existing_ho_paths = {a.content for a in anchors if a.anchor_type == "file_reference" and a.source == "predecessor_handoff"}
            for ho_path in sorted(surviving_paths):
                if ho_path not in existing_ho_paths:
                    anchors.append(
                        Anchor(
                            anchor_id=f"handoff_path:{sha256_text(ho_path)[:8]}",
                            anchor_type="file_reference",
                            source="predecessor_handoff",
                            source_hash=sha256_text(ho_path),
                            content=ho_path,
                            required=True,
                        )
                    )

            # Step 3: Remove inlined files if any
            included_files = []

            # Step 4: Re-render
            current_tail = self._render_task_dynamic_tail(
                task_id, attempt_id, worktree_path, allowed_paths,
                task_requirements, referenced_files, included_files,
                handoffs, validations, task_prompt, retry_info=retry_info
            )
            current_bytes = len(current_tail.encode("utf-8"))

        current_tail = redact_secrets(current_tail)
        current_bytes = len(current_tail.encode("utf-8"))

        stable_prefix, _, _ = StablePrefixManager.get_stable_prefix(role)
        full_rendered_prompt = redact_secrets(stable_prefix + "\n" + current_tail)
        full_packet_bytes = len(full_rendered_prompt.encode("utf-8"))

        # Gate: Strictly verify required anchor recall and secondary exact substring gates before budget check
        verify_required_anchors(anchors, full_rendered_prompt, context_label=f"Task {task_id}")

        # Hard budget check
        if current_bytes > hard_budget:
            raise ContextBudgetExceededError(
                f"CONTEXT_BUDGET_EXCEEDED: Task {task_id} context size ({current_bytes} bytes) exceeds hard budget ({hard_budget} bytes)"
            )

        packet_id = f"ctx-task-{task_id}-att{attempt_id}-{sha256_text(full_rendered_prompt)[:8]}"
        packet_hash = sha256_text(full_rendered_prompt)

        return TaskContextPacket(
            schema_version=SCHEMA_VERSION,
            packet_id=packet_id,
            packet_role=role,
            goal_id=goal_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            source_artifacts=source_artifacts,
            source_hashes=source_hashes,
            requirements=task_requirements,
            required_anchors=anchors,
            included_files=included_files,
            referenced_files=referenced_files,
            dependencies=dependencies,
            handoffs=[h.to_dict() for h in handoffs],
            validations=validations,
            constraints=[],
            budget={
                "soft_budget_bytes": soft_budget,
                "hard_budget_bytes": hard_budget,
                "original_bytes": original_bytes,
                "pruned_bytes": max(0, original_bytes - current_bytes),
                "final_bytes": current_bytes,
                "was_pruned": pruned,
                "pruned_files": dropped_files,
            },
            packet_bytes=full_packet_bytes,
            packet_hash=packet_hash,
            compiler_version=COMPILER_VERSION,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            rendered_tail=current_tail,
            token_count=None,
            token_count_source=None,
        )

    def compile_planner_packet(
        self,
        raw_goal: str,
        goal_id: str,
        project_policy_summary: dict,
        structured_requirements: Optional[List[dict]] = None,
        available_profiles: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
    ) -> PlannerContextPacket:
        """Compiles a PlannerContextPacket for the planning agent."""
        role = "planner"
        role_policy = self.policy.get_role_policy(role)
        soft_budget = role_policy["soft_budget_bytes"]
        hard_budget = role_policy["hard_budget_bytes"]

        stable_prefix, prefix_hash, _ = StablePrefixManager.get_stable_prefix(role)

        raw_goal = (raw_goal or "").strip()
        source_artifacts = ["GOAL.md"] if (self.source.project_root / "GOAL.md").exists() else []
        source_hashes = {
            "raw_goal": sha256_text(raw_goal),
            "stable_prefix": prefix_hash,
            "secret_env": get_secret_env_fingerprint(),
        }

        anchors = [
            Anchor(
                anchor_id="goal:raw",
                anchor_type="requirement",
                source="goal:raw",
                source_hash=sha256_text(raw_goal.strip()),
                content=raw_goal.strip(),
                required=True,
            )
        ]

        inventory = self.source.get_bounded_file_inventory(max_files=50, max_depth=3)

        sections = [
            f"## Autopilot Planning Assignment: `{goal_id}`",
            "\n### Raw Goal Statement:",
            f"```text\n{raw_goal.strip()}\n```",
        ]

        if structured_requirements:
            sections.append("\n### Pre-Structured Acceptance Criteria:")
            for req in structured_requirements:
                validate_criterion_provenance(req)
                cid = req.get("id", "R")
                desc = req.get("description", "")
                sections.append(f"- **{cid}**: {desc}")
                anchors.append(
                    Anchor(
                        anchor_id=f"req:{cid}",
                        anchor_type="requirement",
                        source=f"structured:{cid}",
                        source_hash=sha256_text(desc),
                        content=desc,
                        required=True,
                    )
                )

        if available_profiles:
            sections.append(f"\n### Available Profiles: {', '.join(available_profiles)}")

        if constraints:
            sections.append("\n### Hard Project Constraints:")
            for c in constraints:
                sections.append(f"- {c}")

        if inventory:
            sections.append("\n### Bounded Repository File Inventory:")
            for f in inventory[:30]:
                sections.append(f"- `{f}`")

        tail = "\n".join(sections) + "\n"
        tail = redact_secrets(tail)
        tail_bytes = len(tail.encode("utf-8"))
        original_bytes = tail_bytes
        was_pruned = False

        if tail_bytes > soft_budget and inventory:
            was_pruned = True
            pruned_sections = [
                f"## Autopilot Planning Assignment: `{goal_id}`",
                "\n### Raw Goal Statement:",
                f"```text\n{raw_goal.strip()}\n```",
            ]
            if structured_requirements:
                pruned_sections.append("\n### Pre-Structured Acceptance Criteria:")
                for req in structured_requirements:
                    cid = req.get("id", "R")
                    desc = req.get("description", "")
                    pruned_sections.append(f"- **{cid}**: {desc}")
            if available_profiles:
                pruned_sections.append(f"\n### Available Profiles: {', '.join(available_profiles)}")
            if constraints:
                pruned_sections.append("\n### Hard Project Constraints:")
                for c in constraints:
                    pruned_sections.append(f"- {c}")
            if inventory:
                pruned_sections.append("\n### Bounded Repository File Inventory:")
                for f in inventory[:15]:
                    pruned_sections.append(f"- `{f}`")
            tail = "\n".join(pruned_sections) + "\n"
            tail = redact_secrets(tail)
            tail_bytes = len(tail.encode("utf-8"))

        stable_prefix, _, _ = StablePrefixManager.get_stable_prefix(role)
        full_rendered_prompt = redact_secrets(stable_prefix + "\n" + tail)
        full_packet_bytes = len(full_rendered_prompt.encode("utf-8"))

        recall, missing = calculate_rendered_anchor_recall(anchors, full_rendered_prompt)
        if recall < 1.0:
            raise ContextAnchorMissingError(f"CONTEXT_ANCHOR_MISSING: Planner packet missing required anchors: {missing}")

        if tail_bytes > hard_budget:
            raise ContextBudgetExceededError(f"Planner context exceeded hard budget: {tail_bytes} > {hard_budget}")

        packet_id = f"ctx-plan-{goal_id}-{sha256_text(full_rendered_prompt)[:8]}"
        packet_hash = sha256_text(full_rendered_prompt)

        return PlannerContextPacket(
            schema_version=SCHEMA_VERSION,
            packet_id=packet_id,
            packet_role=role,
            goal_id=goal_id,
            source_artifacts=source_artifacts,
            source_hashes=source_hashes,
            requirements=structured_requirements or [],
            required_anchors=anchors,
            included_files=[],
            referenced_files=inventory[:15] if was_pruned else inventory[:30],
            dependencies=[],
            handoffs=[],
            validations=[],
            constraints=constraints or [],
            budget={
                "soft_budget_bytes": soft_budget,
                "hard_budget_bytes": hard_budget,
                "original_bytes": original_bytes,
                "pruned_bytes": original_bytes - tail_bytes if was_pruned else 0,
                "final_bytes": tail_bytes,
                "was_pruned": was_pruned,
            },
            packet_bytes=full_packet_bytes,
            packet_hash=packet_hash,
            compiler_version=COMPILER_VERSION,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            rendered_tail=tail,
            token_count=None,
            token_count_source=None,
        )

    def compile_plan_review_packet(
        self,
        goal_spec: dict,
        plan: dict,
        project_policy_summary: dict,
        revision_index: int = 0,
    ) -> PlanReviewContextPacket:
        """Compiles a PlanReviewContextPacket for the independent plan reviewer."""
        role = "reviewer"
        role_policy = self.policy.get_role_policy(role)
        soft_budget = role_policy["soft_budget_bytes"]
        hard_budget = role_policy["hard_budget_bytes"]

        stable_prefix, prefix_hash, _ = StablePrefixManager.get_stable_prefix(role)

        clean_goal_spec = redact_secrets(copy.deepcopy(goal_spec))
        clean_plan = redact_secrets(copy.deepcopy(plan))

        source_artifacts = ["goal-spec.json", "plan.json"]
        source_hashes = {
            "goal-spec": sha256_text(canonical_json_dump(clean_goal_spec)),
            "plan": sha256_text(canonical_json_dump(clean_plan)),
            "task_def": sha256_text(canonical_json_dump(clean_plan.get("tasks", []))),
            "retry_info": sha256_text("REVIEWER_ROLE_NO_RETRY"),
            "stable_prefix": prefix_hash,
            "secret_env": get_secret_env_fingerprint(),
        }

        # Build anchors for all criteria and deterministic validations
        anchors = []
        for r in clean_goal_spec.get("acceptance_criteria", []):
            validate_criterion_provenance(r)
            anchors.append(
                Anchor(
                    anchor_id=f"req:{r['id']}",
                    anchor_type="requirement",
                    source=f"goal_spec:{r['id']}",
                    source_hash=sha256_text(r["description"]),
                    content=r["description"],
                    required=True,
                )
            )

        for t in clean_plan.get("tasks", []):
            tid = t.get("task_id", "")
            for v in t.get("validations", []):
                cmd_str = " ".join(v) if isinstance(v, list) else str(v)
                if cmd_str.strip():
                    anchors.append(
                        Anchor(
                            anchor_id=f"val:{tid}:{sha256_text(cmd_str)[:8]}",
                            anchor_type="validation",
                            source=f"task:{tid}",
                            source_hash=sha256_text(cmd_str),
                            content=cmd_str,
                            required=True,
                        )
                    )

        # Compact representation: instead of 16KB uncompacted dump, render clean structured review context
        sections = [
            f"## Plan Review Assignment (Revision #{revision_index})",
            f"### Goal: {clean_goal_spec.get('title', 'Autopilot Goal')}",
            f"**Goal ID**: `{clean_goal_spec.get('goal_id')}`",
            "\n### Acceptance Criteria to Verify:",
        ]
        for r in clean_goal_spec.get("acceptance_criteria", []):
            prov = r.get("provenance", "USER_EXPLICIT")
            sections.append(f"- **{r['id']}** ({prov}): {r.get('description', '')}")

        sections.append("\n### Proposed Orchestration Plan Tasks:")
        for t in clean_plan.get("tasks", []):
            tid = t.get("task_id", "")
            sats = ", ".join(t.get("satisfies", []))
            deps = ", ".join(t.get("dependencies", [])) or "None"
            paths = ", ".join(t.get("allowed_paths", []))
            val_strs = [f"`{' '.join(v)}`" for v in t.get("validations", [])]
            sections.append(f"#### Task `{tid}` ({t.get('task_type', 'backend')})")
            sections.append(f"- **Satisfies**: {sats}")
            sections.append(f"- **Dependencies**: {deps}")
            sections.append(f"- **Allowed Paths**: `{paths}`")
            sections.append(f"- **Validations**: {', '.join(val_strs)}")

        sections.append(f"\n### Project Policy Limits:\n{json.dumps(project_policy_summary, indent=2)}")

        tail = "\n".join(sections) + "\n"
        tail_bytes = len(tail.encode("utf-8"))
        original_bytes = tail_bytes

        # Pruning check
        pruned = False
        if tail_bytes > soft_budget:
            pruned = True
            compact_sections = [
                f"## Plan Review Assignment (Revision #{revision_index})",
                f"### Goal: {clean_goal_spec.get('title', 'Autopilot Goal')}",
                f"**Goal ID**: `{clean_goal_spec.get('goal_id')}`",
                "\n### Acceptance Criteria to Verify:",
            ]
            for r in clean_goal_spec.get("acceptance_criteria", []):
                prov = r.get("provenance", "USER_EXPLICIT")
                compact_sections.append(f"- **{r['id']}** ({prov}): {r.get('description', '')}")

            compact_sections.append("\n### Proposed Orchestration Plan Tasks:")
            for t in clean_plan.get("tasks", []):
                tid = t.get("task_id", "")
                sats = ", ".join(t.get("satisfies", []))
                deps = ", ".join(t.get("dependencies", [])) or "None"
                val_strs = [f"`{' '.join(v) if isinstance(v, list) else str(v)}`" for v in t.get("validations", [])]
                val_part = f", validations: {', '.join(val_strs)}" if val_strs else ""
                compact_sections.append(f"- Task `{tid}`: satisfies `{sats}`, depends on `{deps}`{val_part}")

            compact_sections.append(f"\n### Project Policy Limits:\n{canonical_json_dump(project_policy_summary)}")
            tail = "\n".join(compact_sections) + "\n"

        tail = redact_secrets(tail)
        tail_bytes = len(tail.encode("utf-8"))

        stable_prefix, _, _ = StablePrefixManager.get_stable_prefix(role)
        full_rendered_prompt = redact_secrets(stable_prefix + "\n" + tail)
        full_packet_bytes = len(full_rendered_prompt.encode("utf-8"))

        verify_required_anchors(anchors, full_rendered_prompt, context_label="Plan review packet")

        if tail_bytes > hard_budget:
            raise ContextBudgetExceededError(f"Plan review context exceeded hard budget: {tail_bytes} > {hard_budget}")

        packet_id = f"ctx-rev-{clean_goal_spec.get('goal_id')}-r{revision_index}-{sha256_text(full_rendered_prompt)[:8]}"
        packet_hash = sha256_text(full_rendered_prompt)

        return PlanReviewContextPacket(
            schema_version=SCHEMA_VERSION,
            packet_id=packet_id,
            packet_role=role,
            goal_id=clean_goal_spec.get("goal_id", "unknown"),
            source_artifacts=source_artifacts,
            source_hashes=source_hashes,
            requirements=clean_goal_spec.get("acceptance_criteria", []),
            required_anchors=anchors,
            included_files=[],
            referenced_files=["GOAL.md"] if (self.source.project_root / "GOAL.md").exists() else [],
            dependencies=[],
            handoffs=[],
            validations=[],
            constraints=[],
            budget={
                "soft_budget_bytes": soft_budget,
                "hard_budget_bytes": hard_budget,
                "original_bytes": original_bytes,
                "pruned_bytes": max(0, original_bytes - tail_bytes),
                "final_bytes": tail_bytes,
                "was_pruned": pruned,
            },
            packet_bytes=full_packet_bytes,
            packet_hash=packet_hash,
            compiler_version=COMPILER_VERSION,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            rendered_tail=tail,
            token_count=None,
            token_count_source=None,
        )

    def compile_audit_packet(
        self,
        goal_spec: dict,
        project_policy_summary: dict,
        validation_results: List[dict],
        base_commit: str,
        round_num: int = 0,
    ) -> AuditContextPacket:
        """Compiles an AuditContextPacket for the independent final auditor."""
        role = "auditor"
        role_policy = self.policy.get_role_policy(role)
        soft_budget = role_policy["soft_budget_bytes"]
        hard_budget = role_policy["hard_budget_bytes"]

        stable_prefix, prefix_hash, _ = StablePrefixManager.get_stable_prefix(role)

        source_artifacts = ["goal-spec.json"]
        source_hashes = {
            "goal-spec": sha256_text(canonical_json_dump(goal_spec)),
            "base_commit": sha256_text(base_commit),
            "stable_prefix": prefix_hash,
            "secret_env": get_secret_env_fingerprint(),
        }

        # Build anchors
        anchors = []
        for r in goal_spec.get("acceptance_criteria", []):
            validate_criterion_provenance(r)
            anchors.append(
                Anchor(
                    anchor_id=f"req:{r['id']}",
                    anchor_type="requirement",
                    source=f"goal_spec:{r['id']}",
                    source_hash=sha256_text(r["description"]),
                    content=r["description"],
                    required=True,
                )
            )

        # Get compact git diff (bounded to 4096 bytes)
        diff_text, diff_truncated = self.source.get_git_diff(base_commit, max_bytes=4096)

        # Build validation evidence summary (compact, no unreadably massive logs)
        val_summary = []
        for v in validation_results:
            cmd = " ".join(v.get("command", [])) if isinstance(v.get("command"), list) else str(v.get("command"))
            status = "PASS" if v.get("passed") else f"FAIL (exit {v.get('returncode')})"
            val_summary.append(f"- Task `{v.get('task_id')}`: `{cmd}` -> **{status}**")
            if not v.get("passed") and v.get("stderr"):
                val_summary.append(f"  - Stderr excerpt: `{v.get('stderr').strip()[:200]}`")

        sections = [
            f"## Final Code Audit Assignment (Round #{round_num})",
            f"### Goal: {goal_spec.get('title', 'Autopilot Project')}",
            f"**Goal ID**: `{goal_spec.get('goal_id')}`",
            "\n### Acceptance Criteria to Audit:",
        ]
        for r in goal_spec.get("acceptance_criteria", []):
            prov = r.get("provenance", "USER_EXPLICIT")
            sections.append(f"- **{r['id']}** ({prov}): {r.get('description', '')}")

        sections.append("\n### Deterministic Validation Evidence:")
        sections.extend(val_summary)

        sections.append(f"\n### Git Diff Summary (Base commit `{base_commit[:8]}` to HEAD):")
        sections.append(f"```diff\n{diff_text.strip()}\n```")
        sections.append("\n**Notice**: You have full access to inspect project source code directly on disk in the repository.")

        tail = "\n".join(sections) + "\n"
        tail_bytes = len(tail.encode("utf-8"))

        original_bytes = tail_bytes
        pruned = False
        pruned_bytes = 0
        if tail_bytes > soft_budget:
            pruned = True
            diff_text, _ = self.source.get_git_diff(base_commit, max_bytes=2048)
            sections[-2] = f"```diff\n{diff_text.strip()}\n```"
            tail = "\n".join(sections) + "\n"
            tail_bytes = len(tail.encode("utf-8"))
            pruned_bytes = max(0, original_bytes - tail_bytes)

        tail = redact_secrets(tail)
        tail_bytes = len(tail.encode("utf-8"))

        if tail_bytes > hard_budget:
            raise ContextBudgetExceededError(f"Audit context exceeded hard budget: {tail_bytes} > {hard_budget}")

        stable_prefix, _, _ = StablePrefixManager.get_stable_prefix(role)
        full_rendered_prompt = redact_secrets(stable_prefix + "\n" + tail)
        full_packet_bytes = len(full_rendered_prompt.encode("utf-8"))

        recall, missing = calculate_rendered_anchor_recall(anchors, full_rendered_prompt)
        if recall < 1.0:
            raise ContextAnchorMissingError(f"CONTEXT_ANCHOR_MISSING: Audit packet missing required anchors: {missing}")

        packet_id = f"ctx-aud-{goal_spec.get('goal_id')}-r{round_num}-{sha256_text(full_rendered_prompt)[:8]}"
        packet_hash = sha256_text(full_rendered_prompt)

        return AuditContextPacket(
            schema_version=SCHEMA_VERSION,
            packet_id=packet_id,
            packet_role=role,
            goal_id=goal_spec.get("goal_id", "unknown"),
            source_artifacts=source_artifacts,
            source_hashes=source_hashes,
            requirements=goal_spec.get("acceptance_criteria", []),
            required_anchors=anchors,
            included_files=[],
            referenced_files=["GOAL.md", "README.md"],
            dependencies=[],
            handoffs=[],
            validations=[],
            constraints=[],
            budget={
                "soft_budget_bytes": soft_budget,
                "hard_budget_bytes": hard_budget,
                "original_bytes": original_bytes,
                "pruned_bytes": pruned_bytes,
                "final_bytes": tail_bytes,
                "was_pruned": pruned,
            },
            packet_bytes=full_packet_bytes,
            packet_hash=packet_hash,
            compiler_version=COMPILER_VERSION,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            rendered_tail=tail,
            token_count=None,
            token_count_source=None,
        )


# ==============================================================================
# 9. DERIVED REQUIREMENT AUDIT & TRACEABILITY
# ==============================================================================

class DerivedRequirementAuditor:
    """Audits GoalSpec requirements to classify, validate, and prevent orphan derived requirements."""

    HARD_INVARIANTS = {
        "INVARIANT:STDLIB_ONLY": "Python 3 standard library only (no external packages/pip)",
        "INVARIANT:PATH_SAFETY": "Filesystem operations must strictly respect allowed_paths",
        "INVARIANT:DETERMINISTIC_TESTING": "Verification must run deterministically via standard test runner",
        "INVARIANT:SECRET_REDACTION": "No secrets, tokens, or private credentials may be exposed",
    }

    @classmethod
    def audit_requirements(cls, goal_spec: dict, plan: Optional[dict] = None) -> Dict[str, Any]:
        """Classifies each criterion, validates derivation traceability, and computes metrics.

        Raises:
            OrphanDerivedRequirementError if an un-traced derived requirement is found.
        """
        criteria = goal_spec.get("acceptance_criteria", [])
        explicit_criteria = []
        derived_criteria = []
        orphan_criteria = []

        explicit_ids = {c["id"] for c in criteria if c.get("provenance") in {"USER_EXPLICIT", "MOCK", "TRANSPORT_ONLY", "REAL"}}
        valid_derived_parent_ids = {c["id"] for c in criteria if c.get("provenance") in {"USER_EXPLICIT", "REAL", "MOCK", "TRANSPORT_ONLY"}}
        all_valid_parents = valid_derived_parent_ids.union(set(cls.HARD_INVARIANTS.keys()))

        for c in criteria:
            validate_criterion_provenance(c)
            cid = c["id"]
            prov = c.get("provenance")
            if prov in {"USER_EXPLICIT", "MOCK", "TRANSPORT_ONLY", "REAL"}:
                explicit_criteria.append(c)
            elif prov == "DERIVED":
                # Validate derivation: requires non-empty derived_from and rationale
                parents = c.get("derived_from", [])
                rationale = c.get("rationale", "")
                if not parents or not rationale:
                    orphan_criteria.append(cid)
                    continue

                # Ensure all parents match an existing criterion or defined hard invariant
                valid_trace = bool(parents) and all(p in all_valid_parents for p in parents)
                if not valid_trace:
                    orphan_criteria.append(cid)
                else:
                    derived_criteria.append(c)
            else:
                orphan_criteria.append(cid)

        if orphan_criteria:
            raise OrphanDerivedRequirementError(
                f"ORPHAN_DERIVED_REQUIREMENTS: Found derived criteria without valid parent trace or rationale: {orphan_criteria}"
            )

        total_count = len(criteria)
        exp_count = len(explicit_criteria)
        der_count = len(derived_criteria)
        ratio = (der_count / total_count) if total_count > 0 else 0.0

        tasks_caused = 0
        context_bytes_caused = 0
        if plan and isinstance(plan, dict) and "tasks" in plan:
            der_set = {c["id"] for c in derived_criteria}
            for t in plan.get("tasks", []):
                t_reqs = set(t.get("satisfies", []) + t.get("requirements", []))
                if t_reqs and t_reqs.issubset(der_set):
                    tasks_caused += 1
                    context_bytes_caused += len(canonical_json_dump(t).encode("utf-8"))

        return {
            "audit_status": "OK",
            "explicit_requirement_count": exp_count,
            "derived_requirement_count": der_count,
            "derived_requirement_ratio": round(ratio, 4),
            "orphan_count": len(orphan_criteria),
            "tasks_caused_by_derived_requirements": tasks_caused,
            "context_bytes_caused_by_derived_requirements": context_bytes_caused,
            "explicit_ids": sorted(explicit_ids),
            "derived_ids": [c["id"] for c in derived_criteria],
        }


# ==============================================================================
# 10. PACKET PERSISTENCE & CRASH SAFETY
# ==============================================================================

def save_context_packet(packet: ContextPacket, target: pathlib.Path) -> pathlib.Path:
    """Atomically saves ContextPacket to disk using temp file + rename.

    Supports passing either a target directory or a direct .json file path.
    """
    if target.suffix == ".json":
        storage_dir = target.parent
        target_path = target
    else:
        storage_dir = target
        target_path = storage_dir / f"{packet.packet_id}.json"

    storage_dir.mkdir(parents=True, exist_ok=True)
    temp_path = storage_dir / f"{target_path.stem}.tmp.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(16)}"

    data_str = canonical_json_dump(packet.to_dict())
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(data_str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, target_path)
    try:
        dir_fd = os.open(str(target_path.parent), os.O_RDONLY)
        os.fsync(dir_fd)
        os.close(dir_fd)
    except OSError as exc:
        logging.getLogger("factory").warning("WARNING_DIRECTORY_FSYNC_FAILED: failed to fsync parent directory of %s: %s", target_path, exc)
    except Exception:
        pass
    return target_path


def load_context_packet(packet_file: pathlib.Path) -> ContextPacket:
    """Loads a ContextPacket from disk with secret environment initialization."""
    snapshot_secret_env()
    try:
        data = json.loads(packet_file.read_text(encoding="utf-8"))
    except Exception as e:
        try:
            corrupt_path = packet_file.with_suffix(packet_file.suffix + ".corrupt")
            os.replace(packet_file, corrupt_path)
        except Exception:
            pass
        raise MalformedContextPacketError(f"Failed to parse ContextPacket JSON from {packet_file}: {e}")
    try:
        return ContextPacket.from_dict(data)
    except StaleContextPacketError:
        raise
    except Exception as e:
        try:
            corrupt_path = packet_file.with_suffix(packet_file.suffix + ".corrupt")
            os.replace(packet_file, corrupt_path)
        except Exception:
            pass
        if isinstance(e, MalformedContextPacketError):
            raise
        raise MalformedContextPacketError(f"Invalid ContextPacket structure in {packet_file}: {e}")


def save_handoff_packet(handoff: HandoffPacket, target: pathlib.Path) -> pathlib.Path:
    """Atomically saves HandoffPacket to disk using temp file + rename.

    Supports passing either a target directory or a direct .json file path.
    """
    if target.suffix == ".json":
        storage_dir = target.parent
        target_path = target
    else:
        storage_dir = target
        target_path = storage_dir / f"{handoff.handoff_id}.json"

    storage_dir.mkdir(parents=True, exist_ok=True)
    temp_path = storage_dir / f"{target_path.stem}.tmp.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(16)}"

    data_str = canonical_json_dump(handoff.to_dict())
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(data_str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, target_path)
    try:
        dir_fd = os.open(str(target_path.parent), os.O_RDONLY)
        os.fsync(dir_fd)
        os.close(dir_fd)
    except OSError as exc:
        logging.getLogger("factory").warning("WARNING_DIRECTORY_FSYNC_FAILED: failed to fsync parent directory of %s: %s", target_path, exc)
    except Exception:
        pass
    return target_path


def load_handoff_packet(handoff_file: pathlib.Path) -> HandoffPacket:
    """Loads a HandoffPacket from disk with cryptographic hash verification."""
    try:
        data = json.loads(handoff_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise MalformedContextPacketError(f"Failed to parse HandoffPacket JSON from {handoff_file}: {e}")
    try:
        hp = HandoffPacket.from_dict(data)
    except Exception as e:
        raise MalformedContextPacketError(f"Invalid HandoffPacket structure in {handoff_file}: {e}")

    # Cryptographic integrity check: verify stored hash against raw dict computation
    computed_hash = sha256_text(canonical_json_dump(hp.to_dict_raw()))
    if hp.handoff_hash and computed_hash != hp.handoff_hash:
        raise MalformedContextPacketError(
            f"Handoff integrity verification failed for {hp.handoff_id} in {handoff_file}: stored hash {hp.handoff_hash[:8]} != computed hash {computed_hash[:8]}"
        )
    return hp


# ==============================================================================
# 11. CONTEXT TELEMETRY & CLI COMMANDS
# ==============================================================================

_TELEMETRY_LOCK = threading.Lock()


def record_context_telemetry(run_dir: pathlib.Path, record: dict) -> None:
    """Appends context telemetry record to .agy-factory/evidence/context-telemetry.jsonl with thread-safe locking."""
    evidence_dir = run_dir.parent.parent / "evidence" if run_dir.parent.name == "runs" else run_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    telemetry_file = evidence_dir / "context-telemetry.jsonl"
    bounded_record = {}
    for k, v in record.items():
        if isinstance(v, str) and len(v) > 2048:
            bounded_record[k] = v[:2048]
        else:
            bounded_record[k] = v
    bounded_record["timestamp"] = bounded_record.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    bounded_record["schema_version"] = SCHEMA_VERSION
    line = json.dumps(bounded_record, sort_keys=True) + "\n"
    with _TELEMETRY_LOCK:
        with open(telemetry_file, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass


def cmd_context_inspect(run_id: str, task_id: Optional[str] = None, project_root: Optional[pathlib.Path] = None) -> int:
    """Inspects context packets for a given run and optional task."""
    p_root = project_root or pathlib.Path.cwd()
    run_dir = p_root / ".agy-factory" / "runs" / run_id
    if not run_dir.exists():
        # Check factory root
        run_dir = pathlib.Path(__file__).resolve().parent.parent / ".agy-factory" / "runs" / run_id
    if not run_dir.exists():
        print(f"Error: Run '{run_id}' not found.")
        return 1

    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    packets_dir = run_dir / "context" / "packets"
    found_packets = []
    if packets_dir.exists():
        for pf in sorted(packets_dir.glob("*.json")):
            try:
                found_packets.append(load_context_packet(pf))
            except Exception:
                pass

    # Also search workers directories
    workers_dir = run_dir / "workers"
    if workers_dir.exists():
        for t_dir in sorted(workers_dir.iterdir()):
            if not t_dir.is_dir():
                continue
            for att_dir in sorted(t_dir.glob("att-*")):
                cpf = att_dir / "context_packet.json"
                if cpf.exists() and not any(p.packet_id == cpf.stem for p in found_packets):
                    try:
                        found_packets.append(load_context_packet(cpf))
                    except Exception:
                        pass

    if task_id:
        target = [p for p in found_packets if p.task_id == task_id]
        if not target:
            print(f"No context packet found for task '{task_id}' in run '{run_id}'.")
            return 1
        p = target[-1]
        print(f"================================================================================")
        print(f"Context Packet: {p.packet_id} (Role: {p.packet_role})")
        print(f"================================================================================")
        print(f"Task ID:          {p.task_id} (Attempt #{p.attempt_id})")
        print(f"Goal ID:          {p.goal_id}")
        print(f"Packet Bytes:     {p.packet_bytes} bytes")
        print(f"Budget:           soft={p.budget.get('soft_budget_bytes')}, hard={p.budget.get('hard_budget_bytes')}, was_pruned={p.budget.get('was_pruned')}")
        print(f"Packet Hash:      {p.packet_hash}")
        recall, missing = p.calculate_required_anchor_recall()
        print(f"Anchor Recall:    {recall:.1%} ({len(p.required_anchors)} required anchors)")
        if missing:
            print(f"  Missing: {missing}")
        print(f"Requirements:     {len(p.requirements)} criteria")
        for r in p.requirements:
            print(f"  - [{r.get('id')}]: {r.get('description')}")
        print(f"Referenced Files: {len(p.referenced_files)} files")
        for rf in p.referenced_files:
            print(f"  - {rf}")
        print(f"Included Files:   {len(p.included_files)} inline excerpts")
        print(f"Handoffs:         {len(p.handoffs)} handoffs received")
        print(f"Validations:      {len(p.validations)} validation commands")
        for v in p.validations:
            print(f"  - {' '.join(v)}")
        return 0

    print(f"================================================================================")
    print(f"Context Packets Inspection for Run: {run_id}")
    print(f"================================================================================")
    print(f"{'Role':<10} | {'Task ID':<18} | {'Att':<4} | {'Packet Bytes':<12} | {'Anchors':<8} | {'Recall':<6} | {'Handoffs':<8}")
    print("-" * 80)
    for p in found_packets:
        recall, _ = p.calculate_required_anchor_recall()
        print(f"{p.packet_role:<10} | {p.task_id or '-':<18} | {p.attempt_id or 1:<4} | {p.packet_bytes:<12} | {len(p.required_anchors):<8} | {recall:>5.1%} | {len(p.handoffs):<8}")
    print("=" * 80)
    return 0


def cmd_context_stats(run_id: str, is_json: bool = False, project_root: Optional[pathlib.Path] = None) -> int:
    """Computes redundancy analysis, context byte totals, and token metrics for a run."""
    p_root = project_root or pathlib.Path.cwd()
    run_dir = p_root / ".agy-factory" / "runs" / run_id
    if not run_dir.exists():
        run_dir = pathlib.Path(__file__).resolve().parent.parent / ".agy-factory" / "runs" / run_id
    if not run_dir.exists():
        print(f"Error: Run '{run_id}' not found.")
        return 1

    # Gather all prompt files
    prompt_files = []
    workers_dir = run_dir / "workers"
    if workers_dir.exists():
        for pf in workers_dir.glob("*/att-*/prompt.md"):
            prompt_files.append(pf)

    texts = [pf.read_text(encoding="utf-8") for pf in prompt_files]
    redundancy = calculate_context_redundancy(texts)

    # Collect provider tokens and attempt records
    metrics_file = run_dir / "metrics.json"
    metrics = json.loads(metrics_file.read_text(encoding="utf-8")) if metrics_file.exists() else []

    total_input_tokens = 0
    total_cached_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0
    has_token_data = False

    for m in metrics:
        # Check output.json
        tid = m.get("task_id")
        att = m.get("attempt_id", 1)
        out_f = run_dir / "workers" / tid / f"att-{att}" / "output.json"
        if out_f.exists():
            try:
                out_data = json.loads(out_f.read_text(encoding="utf-8"))
                usage = out_data.get("usage", {})
                if usage:
                    has_token_data = True
                    total_input_tokens += usage.get("input_tokens", 0)
                    total_cached_tokens += usage.get("cache_read_tokens", 0)
                    total_output_tokens += usage.get("output_tokens", 0)
                    total_reasoning_tokens += usage.get("thinking_tokens", 0)
            except Exception:
                pass

    stats = {
        "run_id": run_id,
        "calls_count": len(texts),
        "total_factory_supplied_bytes": redundancy["total_factory_supplied_bytes"],
        "unique_content_bytes": redundancy["unique_content_bytes"],
        "repeated_content_bytes": redundancy["repeated_content_bytes"],
        "redundancy_ratio": redundancy["redundancy_ratio"],
        "provider_tokens": {
            "input_tokens": total_input_tokens if has_token_data else None,
            "cached_input_tokens": total_cached_tokens if has_token_data else None,
            "output_tokens": total_output_tokens if has_token_data else None,
            "reasoning_tokens": total_reasoning_tokens if has_token_data else None,
        }
    }

    if is_json:
        print(canonical_json_dump(stats))
        return 0

    print("================================================================================")
    print(f"Context Efficiency & Redundancy Statistics for Run: {run_id}")
    print("================================================================================")
    print(f"Total Model Calls Measured:   {stats['calls_count']}")
    print(f"Total Factory-Supplied Bytes: {stats['total_factory_supplied_bytes']:,} bytes")
    print(f"Unique Content Bytes:         {stats['unique_content_bytes']:,} bytes")
    print(f"Repeated Content Bytes:       {stats['repeated_content_bytes']:,} bytes")
    print(f"Context Redundancy Ratio:     {stats['redundancy_ratio']:.2%}")
    if has_token_data:
        print("-" * 80)
        print(f"Provider Input Tokens:        {total_input_tokens:,}")
        print(f"Provider Cached Tokens:       {total_cached_tokens:,}")
        print(f"Provider Output Tokens:       {total_output_tokens:,}")
        print(f"Provider Reasoning Tokens:    {total_reasoning_tokens:,}")
    print("================================================================================")
    return 0


def cmd_context_packet(packet_id: str, run_id: Optional[str] = None, project_root: Optional[pathlib.Path] = None) -> int:
    """Inspects an immutable ContextPacket by ID with secret redaction."""
    p_root = project_root or pathlib.Path.cwd()
    search_dirs = [
        p_root / ".agy-factory" / "runs",
        p_root / ".agy-factory" / "goals",
        pathlib.Path(__file__).resolve().parent.parent / ".agy-factory" / "runs",
    ]

    target_file = None
    for sdir in search_dirs:
        if sdir.exists():
            for p in sdir.glob(f"**/{packet_id}.json"):
                target_file = p
                break
        if target_file:
            break

    if not target_file:
        print(f"Error: Context packet '{packet_id}' not found.")
        return 1

    packet = load_context_packet(target_file)
    p_dict = packet.to_dict()

    # Redact sensitive values from all dictionary fields and rendered_tail
    p_dict = redact_secrets(p_dict)
    if "rendered_tail" in p_dict and isinstance(p_dict["rendered_tail"], str):
        p_dict["rendered_tail"] = redact_secrets(p_dict["rendered_tail"])

    print(canonical_json_dump(p_dict))
    return 0

