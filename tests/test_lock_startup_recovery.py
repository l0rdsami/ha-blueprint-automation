"""Run the actual recovery templates/steps with a virtual clock; no HA/device I/O.

This is an isolated policy harness, not a running HA trigger/lifecycle test.
Native blueprint/automation schema validation is performed separately.
"""
from pathlib import Path
import unittest
from types import SimpleNamespace
import yaml
from jinja2 import Environment, StrictUndefined

class Loader(yaml.SafeLoader):
    pass
Loader.add_constructor('!input', lambda loader, node: {'input': loader.construct_scalar(node)})
BLUEPRINT = yaml.load((Path(__file__).parents[1] / 'switchbot_lock_manager.yaml').read_text(), Loader=Loader)
RECOVERY = BLUEPRINT['action'][1]['choose'][0]

class Run:
    def __init__(self, *, enabled=True, people=None, lock='unlocked', delay=10, trigger='startup_away_recovery', now=0):
        self.people = ['person.one', 'person.two'] if people is None else list(people)
        self.states = {p: 'not_home' for p in self.people}
        self.states['lock.front'] = lock
        self.context = dict(people=self.people, lock_entity='lock.front', lock_delay=delay,
                            restart_recovery_enabled=enabled, trigger=SimpleNamespace(id=trigger))
        self.env = Environment(undefined=StrictUndefined)
        self.context.update(states=lambda e: self.states.get(e, 'unknown'),
                            is_state=lambda e, value: self.states.get(e, 'unknown') == value)
        self.steps = RECOVERY['sequence']
        self.index = 0
        self.deadline = None
        self.calls = []
        self.done = not self.check(RECOVERY['conditions'][0]['value_template'])
        self.started_at = now

    def check(self, value):
        return self.env.from_string(value).render(**self.context).strip().lower() == 'true'

    def at(self, now, **changes):
        self.states.update(changes)
        if self.done:
            return
        if self.deadline is not None:
            if now < self.deadline:
                return
            self.deadline = None
        while self.index < len(self.steps):
            step = self.steps[self.index]
            if 'condition' in step:
                if not self.check(step['value_template']):
                    self.done = True
                    return
            elif 'wait_template' in step:
                if not self.check(step['wait_template']):
                    return
            elif 'delay' in step:
                minutes = int(self.env.from_string(step['delay']['minutes']).render(**self.context))
                self.index += 1
                if minutes:
                    self.deadline = now + minutes * 60
                    return
                continue
            elif 'action' in step:
                self.calls.append(step['action'])
            else:
                raise AssertionError(f'Unhandled recovery step: {step}')
            self.index += 1
        self.done = True

class StartupRecoveryTests(unittest.TestCase):
    def test_default_is_disabled(self):
        self.assertIs(BLUEPRINT['blueprint']['input']['restart_recovery_enabled']['default'], False)
        run = Run(enabled=False); run.at(3600)
        self.assertEqual(run.calls, [])

    def test_only_startup_selects_recovery(self):
        for trigger in ['arrived_home', 'left_home', 'night_mode_start', 'night_mode_end',
                        'nfc_tag_scanned', 'open_door_action', 'lock_door_action', 'door_locked']:
            with self.subTest(trigger=trigger):
                run = Run(trigger=trigger); run.at(3600)
                self.assertEqual(run.calls, [])

    def test_fresh_delay_then_lock_once(self):
        run = Run(); run.at(0); run.at(599)
        self.assertEqual(run.calls, [])
        run.at(600); run.at(1200)
        self.assertEqual(run.calls, ['lock.lock'])

    def test_zero_delay(self):
        run = Run(delay=0); run.at(0)
        self.assertEqual(run.calls, ['lock.lock'])

    def test_someone_home_does_not_unlock_or_lock(self):
        run = Run(); run.at(0, **{'person.one': 'home'}); run.at(3600)
        self.assertEqual(run.calls, [])

    def test_empty_people_does_not_lock(self):
        run = Run(people=[]); run.at(0); run.at(3600)
        self.assertTrue(run.done)
        self.assertEqual(run.calls, [])

    def test_invalid_person_waits_then_starts_full_grace(self):
        for state in ['unknown', 'unavailable', '']:
            with self.subTest(state=state):
                run = Run(); run.at(0, **{'person.one': state}); run.at(100)
                self.assertIsNone(run.deadline)
                run.at(120, **{'person.one': 'not_home'})
                self.assertEqual(run.deadline, 720)
                run.at(719); self.assertEqual(run.calls, [])
                run.at(720); self.assertEqual(run.calls, ['lock.lock'])

    def test_missing_person_waits(self):
        run = Run(); del run.states['person.one']; run.at(0); run.at(3600)
        self.assertEqual(run.calls, [])

    def test_unsettled_or_jammed_lock_cannot_authorize(self):
        for state in ['unknown', 'unavailable', 'open', 'jammed', 'locking', 'unlocking']:
            with self.subTest(state=state):
                run = Run(lock=state); run.at(0); run.at(3600)
                self.assertEqual(run.calls, [])

    def test_restore_to_locked_does_nothing(self):
        run = Run(lock='unavailable'); run.at(0); run.at(60, **{'lock.front': 'locked'}); run.at(3600)
        self.assertEqual(run.calls, [])

    def test_restore_to_unlocked_uses_fresh_delay(self):
        run = Run(lock='unavailable'); run.at(0); run.at(60, **{'lock.front': 'unlocked'})
        self.assertEqual(run.deadline, 660)
        run.at(660); self.assertEqual(run.calls, ['lock.lock'])

    def test_arrival_during_grace_is_rechecked(self):
        run = Run(); run.at(0); run.at(300, **{'person.one': 'home'}); run.at(600)
        self.assertEqual(run.calls, [])

    def test_invalid_person_during_grace_is_rechecked(self):
        run = Run(); run.at(0); run.at(300, **{'person.one': 'unavailable'}); run.at(600)
        self.assertEqual(run.calls, [])

    def test_changed_lock_during_grace_is_rechecked(self):
        for state in ['locked', 'jammed', 'unavailable']:
            with self.subTest(state=state):
                run = Run(); run.at(0); run.at(300, **{'lock.front': state}); run.at(600)
                self.assertEqual(run.calls, [])

    def test_named_away_zone_is_valid(self):
        run = Run(); run.at(0, **{'person.one': 'work'}); run.at(600)
        self.assertEqual(run.calls, ['lock.lock'])

    def test_another_restart_extends_grace_explicitly(self):
        # The previous in-memory run is gone. A new startup starts another full delay.
        run = Run(now=240); run.at(240); run.at(600)
        self.assertEqual(run.calls, [])
        run.at(839); self.assertEqual(run.calls, [])
        run.at(840); self.assertEqual(run.calls, ['lock.lock'])

    def test_recovery_has_no_unlock_or_open_action(self):
        calls = [step['action'] for step in RECOVERY['sequence'] if 'action' in step]
        self.assertEqual(calls, ['lock.lock'])
        self.assertEqual(BLUEPRINT['mode'], 'restart')
        self.assertTrue(any(t.get('id') == 'startup_away_recovery' and t.get('event') == 'start'
                            for t in BLUEPRINT['trigger']))

if __name__ == '__main__':
    unittest.main()
