[location_sender.yaml](location_sender.yaml) needs he following rest_command in the `configuration.yaml`

```yaml
rest_command:
  blueprint_webhook_sender:
    url: "{{ url }}"
    method: POST
    payload: '{"lat": "{{ lat }}", "long": "{{ long }}", "acc": "{{ acc }}", "dev_id": "{{ dev_id }}"}'
    content_type: "application/json"
```
