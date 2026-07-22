from pathlib import Path

from conn.lab.atlas import (
    AtlasExposure,
    compile_atlas,
    load_capability_matrix,
    load_command_corpus,
    rank_blockers,
)


ROOT = Path(__file__).resolve().parents[1]

SURFACES = {
    "calendar",
    "finder",
    "firefox",
    "fixture",
    "notes",
    "preview",
    "safari",
    "terminal",
}

JOBS = {
    "app_window_selection",
    "control_activation",
    "collection_selection",
    "field_text_entry",
    "menus_overlays",
    "document_history",
    "named_scroll",
    "visual_fallback",
    "multi_step",
}


def test_capability_matrix_freezes_every_surface_job_pair() -> None:
    matrix = load_capability_matrix(ROOT)

    assert matrix.schema_version == 1
    assert matrix.frozen is True
    assert {row.surface for row in matrix.rows} == SURFACES
    assert {row.job for row in matrix.rows} == JOBS
    assert len(matrix.rows) == len(SURFACES) * len(JOBS)
    assert len({(row.surface, row.job) for row in matrix.rows}) == len(matrix.rows)


def test_top_twenty_corpus_is_fixed_before_atlas_results() -> None:
    corpus = load_command_corpus(ROOT)

    assert corpus.schema_version == 1
    assert corpus.frozen is True
    assert len(corpus.commands) == 20
    assert len({command.id for command in corpus.commands}) == 20
    assert all(command.surface in SURFACES for command in corpus.commands)
    assert all(command.job in JOBS for command in corpus.commands)


def test_atlas_keeps_failed_and_unmeasured_rows_in_the_denominator() -> None:
    matrix = load_capability_matrix(ROOT)
    observations = {
        "finder": {
            "jobs": {
                "app_window_selection": {
                    "bundle_id": "com.apple.finder",
                    "window_present": True,
                },
                "control_activation": {
                    "candidate_count": 3,
                    "total_match_count": 3,
                    "truncated": False,
                },
                "field_text_entry": {
                    "candidate_count": 0,
                    "total_match_count": 0,
                    "truncated": False,
                },
            },
            "conn_outcome": "verified",
        }
    }

    report = compile_atlas(matrix, observations)

    assert len(report.rows) == len(matrix.rows)
    by_key = {(row.surface, row.job): row for row in report.rows}
    assert by_key[("finder", "app_window_selection")].exposure == (
        AtlasExposure.EXPOSED
    )
    assert by_key[("finder", "control_activation")].candidate_count == 3
    assert by_key[("finder", "field_text_entry")].exposure == (
        AtlasExposure.NOT_EXPOSED
    )
    assert by_key[("calendar", "control_activation")].exposure == (
        AtlasExposure.UNMEASURED
    )


def test_blocker_ranking_counts_frozen_rows_without_relabeling() -> None:
    matrix = load_capability_matrix(ROOT)
    report = compile_atlas(matrix, {})

    ranking = rank_blockers(report)

    assert len(ranking) == len(JOBS)
    assert all(item.blocked_surfaces == len(SURFACES) for item in ranking)
