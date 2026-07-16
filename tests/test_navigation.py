from conn.actions import blocked_receipt
from conn.navigation import NavigationEffect, NavigationLease
from conn.tools.native_actions import validate_plan


def test_navigation_lease_defaults_off_and_binds_one_session_and_connection():
    lease = NavigationLease("session-a")

    assert lease.public_snapshot() == {
        "granted": False,
        "active": False,
        "suspended": False,
        "generation": 0,
        "guidance": "Open the Conn menu and click Navigation control: Off.",
    }
    assert lease.grant("session-a", "app-a") is False

    lease.bind_connection("app-a")

    assert lease.grant("session-a", "app-a") is True
    assert lease.allows(NavigationEffect.REVERSIBLE_NAVIGATION, lease.generation)
    assert not lease.allows(NavigationEffect.CONSEQUENTIAL, lease.generation)


def test_navigation_grant_guidance_has_one_policy_owned_source():
    lease = NavigationLease("session-a")
    receipt = blocked_receipt(
        target="Play",
        summary="navigation_grant_required",
        duration_ms=0,
    )

    assert lease.public_snapshot()["guidance"] == (
        "Open the Conn menu and click Navigation control: Off."
    )
    assert receipt.safe_user_message() == lease.public_snapshot()["guidance"]


def test_navigation_lease_refuses_excluded_effect_classes():
    lease = NavigationLease("session-a")
    lease.bind_connection("app-a")
    assert lease.grant("session-a", "app-a")

    for effect in (
        NavigationEffect.CONSEQUENTIAL,
        NavigationEffect.DESTRUCTIVE,
        NavigationEffect.SECURE_OR_DENIED,
        NavigationEffect.UNKNOWN,
    ):
        assert not lease.allows(effect, lease.generation)


def test_revoke_and_suspend_invalidate_prepared_generations():
    lease = NavigationLease("session-a")
    lease.bind_connection("app-a")
    lease.grant("session-a", "app-a")
    prepared = lease.generation

    assert lease.revoke("session-a", "app-a")
    assert not lease.allows(NavigationEffect.REVERSIBLE_NAVIGATION, prepared)

    lease.grant("session-a", "app-a")
    prepared = lease.generation
    assert lease.suspend("session-a", "app-a")
    assert lease.public_snapshot()["suspended"] is True
    assert not lease.allows(NavigationEffect.REVERSIBLE_NAVIGATION, prepared)

    assert lease.resume("session-a", "app-a")
    assert lease.public_snapshot()["active"] is True
    assert lease.public_snapshot()["suspended"] is False
    assert not lease.allows(NavigationEffect.REVERSIBLE_NAVIGATION, prepared)


def test_new_connection_revokes_and_old_disconnect_cannot_touch_newer_lease():
    lease = NavigationLease("session-a")
    lease.bind_connection("app-old")
    lease.grant("session-a", "app-old")

    lease.bind_connection("app-new")
    assert lease.public_snapshot()["active"] is False
    lease.grant("session-a", "app-new")
    current = lease.generation

    assert lease.disconnect("app-old") is False
    assert lease.generation == current
    assert lease.public_snapshot()["active"] is True
    assert lease.disconnect("app-new") is True
    assert lease.public_snapshot()["active"] is False


def test_new_daemon_session_requires_a_fresh_pointer_grant():
    lease = NavigationLease("session-a")
    lease.bind_connection("app-a")
    lease.grant("session-a", "app-a")

    lease.begin_session("session-b")

    assert lease.public_snapshot()["active"] is False
    assert lease.grant("session-a", "app-a") is False
    assert lease.grant("session-b", "app-a") is True


def test_duplicate_lease_messages_are_idempotent():
    lease = NavigationLease("session-a")
    lease.bind_connection("app-a")
    lease.grant("session-a", "app-a")
    granted = lease.generation
    lease.grant("session-a", "app-a")
    assert lease.generation == granted

    lease.suspend("session-a", "app-a")
    suspended = lease.generation
    lease.suspend("session-a", "app-a")
    assert lease.generation == suspended

    lease.resume("session-a", "app-a")
    resumed = lease.generation
    lease.resume("session-a", "app-a")
    assert lease.generation == resumed


def test_stale_resume_cannot_clear_a_newer_suspension():
    lease = NavigationLease("session-a")
    lease.bind_connection("app-a")
    lease.grant("session-a", "app-a")
    old_generation = lease.generation
    lease.suspend("session-a", "app-a")

    assert lease.resume(
        "session-a", "app-a", expected_generation=old_generation
    ) is False
    assert lease.public_snapshot()["suspended"] is True


def test_navigation_bound_plan_requires_compiler_effect_and_generation():
    plan = {
        "plan_fingerprint": "fingerprint",
        "preview": "Press Play",
        "target": "Play",
        "effect": "value changes",
        "authorized_strategies": ["ax_press"],
    }

    assert validate_plan(plan, require_navigation=True) == (
        "native_plan_invalid: missing effect class"
    )
    plan["effect_class"] = "reversible_navigation"
    assert validate_plan(plan, require_navigation=True) == (
        "native_plan_invalid: missing navigation generation"
    )
    plan["navigation_generation"] = 3
    assert validate_plan(plan, require_navigation=True) is None
