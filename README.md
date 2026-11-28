Add files to your instance by adding<br>
`https://raw.githubusercontent.com/l0rdsami/ha-blueprint-automation/refs/heads/main/[file_name]`<br>
for Example:<br>
`https://raw.githubusercontent.com/l0rdsami/ha-blueprint-automation/refs/heads/main/location_receiver.yaml`


[location_sender.yaml](location_sender.yaml) needs he following rest_command in the `configuration.yaml`

```yaml
rest_command:
  blueprint_webhook_sender:
    url: "{{ url }}"
    method: POST
    payload: '{"lat": "{{ lat }}", "long": "{{ long }}", "acc": "{{ acc }}", "dev_id": "{{ dev_id }}"}'
    content_type: "application/json"
```


## Optional lock recovery after a Home Assistant restart

`switchbot_lock_manager.yaml` has an opt-in **Recheck Away Locking After Restart**
setting, disabled by default. When enabled, it waits for every tracked person and
the lock to have valid states. If everyone is explicitly away and the lock is
unlocked, it waits a fresh configured auto-lock delay and checks those states
again before locking. A normal arrival or manual lock cancels the pending run
through the existing restart-mode triggers. Unknown/unavailable people and
transient, unavailable, open or jammed lock states cannot authorize recovery.

This reconciles the current away state after startup; it does **not** persist an
original departure deadline or assume that an earlier countdown existed. Every
restart can extend the grace period. It adds no startup unlock/open action and
does not change the existing daytime, night, notification-action or NFC policy.
An exact remaining-deadline feature would require separate persistent state and
is outside this proposal.

Run the isolated policy tests with `python3 -m unittest discover -s tests -v`.
The tests require PyYAML and Jinja2 and send no Home Assistant/device commands.
