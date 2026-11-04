# Verifica todas las transiciones, dedupe concurrente y resolución basada en observaciones.
import asyncio
from itertools import product

import pytest

from backend.alert_lifecycle import AlertStore, IllegalTransition, TRANSITIONS, transition
from backend.config import AlertConfig
from backend.risk import Assessment

CRITICAL = Assessment("critical", ("horizontal_torso", "immobile"))
OK = Assessment("ok", ())
ALL_PAIRS = list(product(["OPEN", "ACKNOWLEDGED", "RESOLVED"], ["acknowledge", "auto_resolve", "expire"]))


@pytest.mark.parametrize("state,event", ALL_PAIRS)
def test_every_legal_and_illegal_transition(state, event):
    if (state, event) in TRANSITIONS:
        assert transition(state, event) == TRANSITIONS[(state, event)]
    else:
        with pytest.raises(IllegalTransition):
            transition(state, event)


def test_unknown_state_and_event_are_illegal():
    with pytest.raises(IllegalTransition):
        transition("UNKNOWN", "acknowledge")
    with pytest.raises(IllegalTransition):
        transition("OPEN", "unknown")


def test_dedupe_for_open_and_acknowledged_then_reopen(sink):
    async def run():
        store = AlertStore(AlertConfig(expire_seconds=10), sink)
        results = await asyncio.gather(*(store.open(CRITICAL, 0) for _ in range(5)))
        alert = next(result for result in results if result)
        assert sum(result is not None for result in results) == 1
        await store.acknowledge(alert.id, 1)
        assert await store.open(CRITICAL, 2) is None
        await store.expire(10)
        assert store.history[alert.id].state == "RESOLVED"
        assert (await store.open(CRITICAL, 10)).id != alert.id
    asyncio.run(run())


@pytest.mark.parametrize("acknowledged", [False, True])
def test_auto_resolve_requires_continuous_observed_ok(sink, acknowledged):
    async def run():
        store = AlertStore(AlertConfig(auto_resolve_seconds=3), sink)
        alert = await store.open(CRITICAL, 0)
        if acknowledged:
            await store.acknowledge(alert.id, 0.5)
        await store.observe(OK, 1)
        await store.observe(CRITICAL, 3)
        await store.observe(OK, 4)
        await store.observe(None, 5)
        await store.observe(Assessment("ok", ("no_pose",)), 9)
        assert store.history[alert.id].state != "RESOLVED"
        await store.observe(OK, 10)
        await store.observe(OK, 12.9)
        assert store.history[alert.id].state != "RESOLVED"
        await store.observe(OK, 13)
        assert store.history[alert.id].event == "auto_resolve"
    asyncio.run(run())


def test_late_vision_preserves_state_and_history_is_bounded(sink):
    async def run():
        store = AlertStore(AlertConfig(expire_seconds=2, history_size=1), sink)
        alert = await store.open(CRITICAL, 0)
        await store.acknowledge(alert.id, 1)
        await store.set_vision(alert.id, "synthetic answer", None, 1.5)
        assert store.history[alert.id].state == "ACKNOWLEDGED"
        await store.expire(2)
        await store.set_vision(alert.id, None, "synthetic failure", 3)
        assert store.history[alert.id].state == "RESOLVED"
        await store.open(CRITICAL, 4)
        await store.set_vision(alert.id, "discarded", None, 5)
        assert len(store.history) == 1 and alert.id not in store.history
    asyncio.run(run())
