"""The connector rules in the system prompt follow the tools a session exports.
A rule naming a tool the model cannot call invites a refusal or a made-up answer."""

from __future__ import annotations

from conn import intent_eval
from conn.prompt import BASE_INSTRUCTIONS, INSTRUCTIONS, connector_section, instructions_for
from conn.tools.registry import build_registry, export_openai

HEADER = "# Your day, people and meetings"


def test_no_connector_tools_means_no_connector_section():
    tools = export_openai(build_registry())
    text = instructions_for(tools)
    assert HEADER not in text
    assert "phoenix_people" not in text and "Granola" not in text
    assert "{connectors}" not in text
    assert text == BASE_INSTRUCTIONS.replace("{connectors}", "")


def test_eval_fixtures_get_the_full_section():
    tools = export_openai(intent_eval.eval_registry())
    assert instructions_for(tools) == INSTRUCTIONS
    assert HEADER in INSTRUCTIONS
    assert "search both Granola and Wispr" in INSTRUCTIONS


def test_lines_follow_their_tools():
    only_phoenix_reads = connector_section(["phoenix_people", "phoenix_today"])
    assert "use phoenix_people first." in only_phoenix_reads
    assert "Search mail" not in only_phoenix_reads
    assert "Never capture" not in only_phoenix_reads
    assert "Granola" not in only_phoenix_reads

    one_meeting_source = connector_section(["wispr_search_meetings"])
    assert "search Wispr." in one_meeting_source
    assert "Granola" not in one_meeting_source

    writes = connector_section(["phoenix_remind"])
    assert "Capture or remind only when he asks for it." in writes

    mail_only = connector_section(["superhuman_search_threads"])
    assert "Search mail when he asks about a specific email, sender, or kind of email" in mail_only
    assert "phoenix_people" not in mail_only


def test_native_tools_sharing_a_prefix_add_nothing():
    assert connector_section([]) == ""
    text = instructions_for(["computer_create", "shortcuts_run", "phoenix_search", "phoenix_open_note"])
    assert HEADER not in text
