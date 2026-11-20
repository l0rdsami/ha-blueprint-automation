"""Vacancy regression fixtures; no Home Assistant services or devices are used.

Run with: python -m unittest discover -s tests -v
Install dependencies with: pip install -r tests/requirements.txt

The fixture renders the blueprint's actual occupancy predicates and models its
restart/delay behavior. It is not a full Home Assistant integration test.
"""

from pathlib import Path
from types import SimpleNamespace
import unittest

from jinja2.nativetypes import NativeEnvironment
import yaml


class BlueprintLoader(yaml.SafeLoader):
    """Allow unresolved !input values while inspecting the blueprint."""


BlueprintLoader.add_constructor(
    "!input", lambda loader, node: {"input": loader.construct_scalar(node)}
)
BLUEPRINT = yaml.load(
    (Path(__file__).resolve().parents[1] / "presencelight.yaml").read_text(),
    Loader=BlueprintLoader,
)


def evaluate(template, states, **variables):
    result = NativeEnvironment().from_string(template).render(
        is_state=lambda entity, value: states.get(entity, "unknown") == value,
        expand=lambda entities: [
            SimpleNamespace(state=states.get(entity, "unknown"))
            for entity in entities
        ],
        **variables,
    )
    if isinstance(result, str) and result.strip() in ("True", "False"):
        return result.strip() == "True"
    return result


class PresenceFixture:
    """Inject sensor transitions and advance a synthetic clock."""

    def __init__(self, states=None, activation_allowed=True, grace=40):
        self.states = states or {"binary_sensor.a": "on"}
        self.activation_allowed = activation_allowed
        self.grace = grace
        self.deadline = None
        self.actions = []
        self.now = 0

    def event(self, entity=None, value=None, startup=False):
        # HA restart mode cancels the old run before branch-local conditions.
        self.deadline = None
        if entity:
            self.states[entity] = value
        trigger = SimpleNamespace(
            id="startup" if startup else "presence_changed",
            to_state=None if startup else SimpleNamespace(state=value),
        )
        branches = BLUEPRINT["action"][0]["choose"]
        context = {"presence_entities": list(self.states), "trigger": trigger}
        if evaluate(
            branches[0]["conditions"][0]["value_template"], self.states, **context
        ):
            if self.activation_allowed:
                self.actions.append("on")
        elif evaluate(
            branches[1]["conditions"][0]["value_template"], self.states, **context
        ):
            self.deadline = self.now + self.grace

    def advance(self, seconds):
        self.now += seconds
        if self.deadline is None or self.now < self.deadline:
            return
        guard = BLUEPRINT["action"][0]["choose"][1]["sequence"][1]["value_template"]
        if evaluate(guard, self.states, presence_entities=list(self.states)):
            self.actions.append("off")
        self.deadline = None


class PresenceTests(unittest.TestCase):
    def test_every_state_change_can_cancel_a_pending_off(self):
        self.assertEqual(BLUEPRINT["mode"], "restart")
        self.assertEqual(BLUEPRINT["condition"], [])
        self.assertIsNone(BLUEPRINT["trigger"][0]["to"])

    def test_one_vacancy_interval(self):
        fixture = PresenceFixture()
        fixture.event("binary_sensor.a", "off")
        fixture.advance(39)
        self.assertEqual(fixture.actions, [])
        fixture.advance(1)
        self.assertEqual(fixture.actions, ["off"])

    def test_return_during_grace_cancels_off(self):
        fixture = PresenceFixture()
        fixture.event("binary_sensor.a", "off")
        fixture.advance(30)
        fixture.event("binary_sensor.a", "on")
        fixture.advance(50)
        self.assertEqual(fixture.actions, ["on"])

    def test_activation_veto_does_not_prevent_cancellation(self):
        fixture = PresenceFixture(activation_allowed=False)
        fixture.event("binary_sensor.a", "off")
        fixture.advance(30)
        fixture.event("binary_sensor.a", "on")
        fixture.advance(50)
        self.assertEqual(fixture.actions, [])

    def test_unavailable_sensor_cancels_pending_off(self):
        fixture = PresenceFixture()
        fixture.event("binary_sensor.a", "off")
        fixture.advance(20)
        fixture.event("binary_sensor.a", "unavailable")
        fixture.advance(60)
        self.assertEqual(fixture.actions, [])

    def test_all_sensors_must_be_clear(self):
        fixture = PresenceFixture({"binary_sensor.a": "on", "binary_sensor.b": "on"})
        fixture.event("binary_sensor.a", "off")
        fixture.advance(60)
        self.assertEqual(fixture.actions, [])
        fixture.event("binary_sensor.b", "off")
        fixture.advance(40)
        self.assertEqual(fixture.actions, ["off"])

    def test_startup_clear_with_zero_delay(self):
        fixture = PresenceFixture({"binary_sensor.a": "off"}, grace=0)
        fixture.event(startup=True)
        fixture.advance(0)
        self.assertEqual(fixture.actions, ["off"])

    def test_unknown_on_startup_never_means_clear(self):
        fixture = PresenceFixture({"binary_sensor.a": "unknown"})
        fixture.event(startup=True)
        fixture.advance(500)
        self.assertEqual(fixture.actions, [])


if __name__ == "__main__":
    unittest.main()
