"""Slot model helpers — derive ordered slot lists from config."""
from __future__ import annotations

from typing import List, Optional

from app.config_loader import SlotsConfig, SlotDefinition


def get_required_slots(user_type: str, slots_config: SlotsConfig) -> List[str]:
    """
    Return ordered list of required slot names for a user_type.
    client_name is always index 0, contact always index 1,
    remaining slots follow their order in slots.yaml.
    """
    slots = slots_config.user_types[user_type].required_slots

    def sort_key(s: SlotDefinition) -> int:
        if s.name == "client_name":
            return 0
        if s.name == "contact":
            return 1
        return 2

    ordered = sorted(slots, key=sort_key)
    return [s.name for s in ordered]


def get_slot_definition(
    slot_name: str, user_type: str, slots_config: SlotsConfig
) -> Optional[SlotDefinition]:
    """Return the SlotDefinition for a given slot name and user type."""
    all_slots = (
        slots_config.user_types[user_type].required_slots
        + slots_config.user_types[user_type].optional_slots
    )
    return next((s for s in all_slots if s.name == slot_name), None)


def get_slot_question(slot_name: str, user_type: str, slots_config: SlotsConfig) -> str:
    """Return the question string for a slot, or a generic fallback."""
    defn = get_slot_definition(slot_name, user_type, slots_config)
    if defn:
        return defn.question
    return f"Could you tell me your {slot_name.replace('_', ' ')}?"


def is_contact_form_slot(slot_name: str, user_type: str, slots_config: SlotsConfig) -> bool:
    """Return True if this slot should trigger the contact form widget."""
    defn = get_slot_definition(slot_name, user_type, slots_config)
    return defn is not None and defn.input_type == "contact_form"
