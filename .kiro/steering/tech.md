# Tech Stack

## Languages and runtimes

- Python 3.10+ for every component.
- Pydantic for config models and the Nova Act `act_get` schema.

## Components and libraries

| Component | Technology |
|---|---|
| Listener (Pi) | scapy for ARP/DHCP sniffing, pcap-file input for tests |
| Agent service (Pi) | FastAPI, SQLite, httpx for outbound HTTP and the ntfy JSON stream |
| Status page | Served by the agent service, live updates (SSE or WebSocket, design decides) |
| Buyer | Nova Act SDK workflow on AWS AgentCore Runtime, using AgentCore Browser |
| Notifier | ntfy (self-hosted or ntfy.sh), JSON action buttons, access-token auth |
| CLI | `undash` with `setup` and `discover` subcommands |
| Config | YAML, validated at load |
| Image | CustomPiOS minimal image built by a GitHub Action |
| AWS provisioning | IaC (CDK or CloudFormation, design picks one) |
| Tests | pytest |

## Architecture constraints

- No x86 host. The Pi runs the listener and the agent service only.
- The agent service invokes the buyer workflow with an IAM credential that can invoke one AgentCore Runtime endpoint and nothing else.
- Buyer sessions start from an AgentCore Browser profile that holds the Amazon login.
- Secrets come from environment variables: Nova Act API key, ntfy access token, AWS credentials. Secrets are never written to config files, logs, or the SQLite database.
- Buyer tests use Python-level fakes of the workflow client.

## Conventions

- Every outbound HTTP request and every cloud browser session sets a user agent containing `Agent/ghostshopper`.
- Order rules and the state machine are pure functions with no I/O, so pytest covers them directly.
- Order states: pressed, quoted, awaiting_approval, approved, ordering, placed, denied, expired, failed.

```python
USER_AGENT = "ghostshopper/0.1 Agent/ghostshopper"

# Shape of the JSON body an ntfy action button POSTs to the reply topic.
reply_body = {"order_id": "…", "token": "…", "decision": "approve"}  # or "deny"
```

## Commands

- Tests: `pytest`
- Lint/format tooling is chosen in the design.
