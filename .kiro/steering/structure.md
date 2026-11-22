# Project Structure

Planned layout. The design phase finalizes names.

```
GhostShopper/
├── README.md
├── pyproject.toml
├── config.example.yaml
├── src/ghostshopper/
│   ├── listener/        # scapy sniffer, debounce, pcap input, event POST
│   ├── agent/           # FastAPI app, SQLite store, ntfy subscriber, status page
│   ├── rules/           # pure-Python order rules and state machine (no I/O)
│   ├── buyer/           # Nova Act workflow, Pydantic schemas, workflow client interface
│   ├── notifier/        # ntfy publisher, action-button payloads, token handling
│   ├── config/          # YAML loading and validation
│   └── cli/             # `undash setup`, `undash discover`
├── infra/               # IaC for AgentCore, IAM least-privilege identity
├── image/               # CustomPiOS module and config
├── .github/workflows/   # Pi image build (workflow_dispatch and tags v*)
├── tests/
│   ├── rules/           # rules and state machine
│   ├── listener/        # pcap fixtures
│   ├── agent/
│   ├── buyer/           # fakes of the workflow client
│   └── fixtures/
└── .kiro/
    ├── steering/        # product.md, tech.md, structure.md
    └── specs/ghostshopper/
```

## Boundaries

- `rules/` imports nothing from `agent/`, `buyer/`, or network libraries.
- `buyer/` exposes a workflow client interface. The agent service depends on the interface, so tests inject fakes.
- Only `listener/` imports scapy.
- Only `infra/` contains AWS resource definitions.
