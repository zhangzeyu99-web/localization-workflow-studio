"""Curated rules and observed-term experience stores: load, sanitize, save, apply."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from glossary_extraction.constants import (
    CURATED_VERSION,
    DEFAULT_LEGACY_EXPERIENCE_STORE,
    HIGH_CONFUSION_TERMS,
    OBSERVATION_VERSION,
)
from glossary_extraction.heuristics import (
    choose_en2_value,
    clean_text,
    counter_to_dict,
    dict_to_counter,
    merge_counters,
)


def new_curated_rules() -> dict[str, Any]:
    return {"version": CURATED_VERSION, "terms": {}}


def new_observation_store() -> dict[str, Any]:
    return {"version": OBSERVATION_VERSION, "terms": {}}


def split_legacy_term_memory(memory: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    curated = new_curated_rules()
    observations = new_observation_store()
    if not isinstance(memory, dict):
        return curated, observations

    for term, raw_state in memory.get("terms", {}).items():
        if not isinstance(raw_state, dict):
            continue
        curated_state = {
            "approved_en": clean_text(raw_state.get("approved_en")),
            "approved_en2": clean_text(raw_state.get("approved_en2")),
            "block_en2": bool(raw_state.get("block_en2")),
            "ignore": bool(raw_state.get("ignore")),
            "note": clean_text(raw_state.get("note")),
            "category_override": clean_text(raw_state.get("category_override")),
            "term_type_override": clean_text(raw_state.get("term_type_override")),
        }
        observation_state = {
            "observed_exact_candidates": counter_to_dict(dict_to_counter(raw_state.get("observed_exact_candidates"))),
            "observed_example_usages": counter_to_dict(dict_to_counter(raw_state.get("observed_example_usages"))),
            "observed_manual_adaptations": counter_to_dict(dict_to_counter(raw_state.get("observed_manual_adaptations"))),
            "seen_runs": max(0, int(raw_state.get("seen_runs", 0) or 0)),
            "last_seen_at": clean_text(raw_state.get("last_seen_at")),
            "last_input_digest": clean_text(raw_state.get("last_input_digest")),
        }
        if any(
            [
                curated_state["approved_en"],
                curated_state["approved_en2"],
                curated_state["block_en2"],
                curated_state["ignore"],
                curated_state["note"],
                curated_state["category_override"],
                curated_state["term_type_override"],
            ]
        ):
            curated["terms"][term] = curated_state
        if any(
            [
                observation_state["observed_exact_candidates"],
                observation_state["observed_example_usages"],
                observation_state["observed_manual_adaptations"],
                observation_state["seen_runs"],
                observation_state["last_seen_at"],
                observation_state["last_input_digest"],
            ]
        ):
            observations["terms"][term] = observation_state
    return curated, observations


def load_json_object(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def legacy_experience_candidate(path: Path | None) -> Path | None:
    if path is None:
        return None
    candidate = path.with_name("term_memory.json")
    if candidate.exists():
        return candidate
    if DEFAULT_LEGACY_EXPERIENCE_STORE.exists():
        return DEFAULT_LEGACY_EXPERIENCE_STORE
    return None


def default_curated_term_state() -> dict[str, Any]:
    return {
        "approved_en": "",
        "approved_en2": "",
        "block_en2": False,
        "ignore": False,
        "note": "",
        "category_override": "",
        "term_type_override": "",
    }


def get_curated_term_state(curated_rules: dict[str, Any], term: str, *, create: bool = True) -> dict[str, Any]:
    terms = curated_rules.setdefault("terms", {})
    if create:
        state = terms.setdefault(term, {})
    else:
        state = terms.get(term, {})
        if not isinstance(state, dict):
            state = {}
    defaults = default_curated_term_state()
    if create:
        for key, value in defaults.items():
            state.setdefault(key, value)
        return state
    defaults.update(
        {
            "approved_en": clean_text(state.get("approved_en")),
            "approved_en2": clean_text(state.get("approved_en2")),
            "block_en2": bool(state.get("block_en2")),
            "ignore": bool(state.get("ignore")),
            "note": clean_text(state.get("note")),
            "category_override": clean_text(state.get("category_override")),
            "term_type_override": clean_text(state.get("term_type_override")),
        }
    )
    state = defaults
    return state


def get_observation_term_state(observations_store: dict[str, Any], term: str) -> dict[str, Any]:
    terms = observations_store.setdefault("terms", {})
    state = terms.setdefault(term, {})
    state.setdefault("observed_exact_candidates", {})
    state.setdefault("observed_manual_adaptations", {})
    state.setdefault("observed_example_usages", {})
    state.setdefault("seen_runs", 0)
    state.setdefault("last_seen_at", "")
    state.setdefault("last_input_digest", "")
    return state


def sanitize_curated_rules(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return new_curated_rules()
    if "terms" not in payload or not isinstance(payload["terms"], dict):
        payload = {"version": payload.get("version", CURATED_VERSION), "terms": {}}
    curated = new_curated_rules()
    curated["version"] = int(payload.get("version", CURATED_VERSION) or CURATED_VERSION)
    for term in payload["terms"]:
        if not isinstance(term, str):
            continue
        state = get_curated_term_state(curated, term)
        raw = payload["terms"].get(term)
        if isinstance(raw, dict):
            state["approved_en"] = clean_text(raw.get("approved_en"))
            state["approved_en2"] = clean_text(raw.get("approved_en2"))
            state["block_en2"] = bool(raw.get("block_en2"))
            state["ignore"] = bool(raw.get("ignore"))
            state["note"] = clean_text(raw.get("note"))
            state["category_override"] = clean_text(raw.get("category_override"))
            state["term_type_override"] = clean_text(raw.get("term_type_override"))
    return curated


def sanitize_observation_store(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return new_observation_store()
    if "terms" not in payload or not isinstance(payload["terms"], dict):
        payload = {"version": payload.get("version", OBSERVATION_VERSION), "terms": {}}
    observations = new_observation_store()
    observations["version"] = int(payload.get("version", OBSERVATION_VERSION) or OBSERVATION_VERSION)
    for term in payload["terms"]:
        if not isinstance(term, str):
            continue
        state = get_observation_term_state(observations, term)
        raw = payload["terms"].get(term)
        if isinstance(raw, dict):
            state["observed_exact_candidates"] = counter_to_dict(dict_to_counter(raw.get("observed_exact_candidates")))
            state["observed_example_usages"] = counter_to_dict(dict_to_counter(raw.get("observed_example_usages")))
            state["observed_manual_adaptations"] = counter_to_dict(dict_to_counter(raw.get("observed_manual_adaptations")))
            state["seen_runs"] = max(0, int(raw.get("seen_runs", 0) or 0))
            state["last_seen_at"] = clean_text(raw.get("last_seen_at"))
            state["last_input_digest"] = clean_text(raw.get("last_input_digest"))
    return observations


def load_curated_rules(path: Path | None) -> dict[str, Any]:
    payload = load_json_object(path)
    if payload:
        if any(
            isinstance(state, dict) and any(key.startswith("observed_") for key in state.keys())
            for state in payload.get("terms", {}).values()
        ):
            legacy_curated, _legacy_observations = split_legacy_term_memory(payload)
            return legacy_curated
        return sanitize_curated_rules(payload)

    legacy_path = legacy_experience_candidate(path)
    if legacy_path:
        legacy_payload = load_json_object(legacy_path)
        if legacy_payload:
            legacy_curated, _legacy_observations = split_legacy_term_memory(legacy_payload)
            return legacy_curated
    return new_curated_rules()


def load_observation_store(path: Path | None) -> dict[str, Any]:
    payload = load_json_object(path)
    if payload:
        if any(
            isinstance(state, dict)
            and any(
                key.startswith("approved_")
                or key in {"block_en2", "ignore", "note", "category_override", "term_type_override"}
                for key in state.keys()
            )
            for state in payload.get("terms", {}).values()
        ):
            _legacy_curated, legacy_observations = split_legacy_term_memory(payload)
            return legacy_observations
        return sanitize_observation_store(payload)

    legacy_path = legacy_experience_candidate(path)
    if legacy_path:
        legacy_payload = load_json_object(legacy_path)
        if legacy_payload:
            _legacy_curated, legacy_observations = split_legacy_term_memory(legacy_payload)
            return legacy_observations
    return new_observation_store()


def save_curated_rules(path: Path | None, curated_rules: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_curated_rules(curated_rules), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_observation_store(path: Path | None, observations_store: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_observation_store(observations_store), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_observation_history(
    observation_state: dict[str, Any],
    exact_translation_counter: Counter[str],
    example_usage_counter: Counter[str],
    manual_adaptation_counter: Counter[str],
) -> tuple[Counter[str], Counter[str], Counter[str]]:
    historical_exact = dict_to_counter(observation_state.get("observed_exact_candidates"))
    historical_examples = dict_to_counter(observation_state.get("observed_example_usages"))
    historical_manual = dict_to_counter(observation_state.get("observed_manual_adaptations"))
    return (
        merge_counters(exact_translation_counter, historical_exact),
        merge_counters(example_usage_counter, historical_examples),
        merge_counters(manual_adaptation_counter, historical_manual),
    )


def choose_primary_translation(
    current_counter: Counter[str],
    curated_state: dict[str, Any],
) -> tuple[str, str, list[str]]:
    current = current_counter.most_common(1)[0][0] if current_counter else ""
    approved = clean_text(curated_state.get("approved_en"))
    conflicts = [approved] if current and approved and approved != current else []
    if current:
        return current, "current_table", conflicts
    if approved:
        return approved, "curated", []
    return "", "none", []


def apply_curated_preferences(
    curated_state: dict[str, Any],
    term: str,
    suggested_en: str,
    example_en: str,
    en2_value: str,
    exact_translation_counter: Counter[str],
    example_usage_counter: Counter[str],
    manual_adaptation_counter: Counter[str],
) -> tuple[str, str, str, Counter[str], Counter[str], Counter[str]]:
    approved_en2 = clean_text(curated_state.get("approved_en2"))
    block_en2 = bool(curated_state.get("block_en2"))

    if approved_en2:
        en2_value = approved_en2
    elif block_en2:
        en2_value = ""
    elif not en2_value and manual_adaptation_counter:
        en2_value = choose_en2_value(
            example_en=example_en,
            exact_diff_counter=Counter(),
            manual_counter=manual_adaptation_counter,
        )

    if curated_state.get("ignore") and term not in HIGH_CONFUSION_TERMS:
        return "", "", "", Counter(), Counter(), Counter()
    return suggested_en, example_en, en2_value, exact_translation_counter, example_usage_counter, manual_adaptation_counter


def update_observation_store(
    observation_state: dict[str, Any],
    *,
    input_digest: str,
    exact_translation_counter: Counter[str],
    example_usage_counter: Counter[str],
    manual_adaptation_counter: Counter[str],
) -> None:
    if observation_state.get("last_input_digest") == input_digest:
        observation_state["last_seen_at"] = datetime.now(timezone.utc).isoformat()
        return

    observed_exact = dict_to_counter(observation_state.get("observed_exact_candidates"))
    observed_example = dict_to_counter(observation_state.get("observed_example_usages"))
    observed_manual = dict_to_counter(observation_state.get("observed_manual_adaptations"))
    observed_exact.update(exact_translation_counter)
    observed_example.update(example_usage_counter)
    observed_manual.update(manual_adaptation_counter)

    observation_state["observed_exact_candidates"] = counter_to_dict(observed_exact)
    observation_state["observed_example_usages"] = counter_to_dict(observed_example)
    observation_state["observed_manual_adaptations"] = counter_to_dict(observed_manual)
    observation_state["seen_runs"] = int(observation_state.get("seen_runs", 0)) + 1
    observation_state["last_seen_at"] = datetime.now(timezone.utc).isoformat()
    observation_state["last_input_digest"] = input_digest
