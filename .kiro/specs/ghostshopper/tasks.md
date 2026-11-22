# Implementation Plan: GhostShopper

## Overview

Python 3.10+ throughout (Pi packages) and Python 3.13 for the Buyer runtime. The plan runs the AWS spikes first: spike 1 (user agent over CDP) is task 1 and gates everything that depends on Requirement 15. Spikes 2 to 4 follow before the Buyer runtime and the packaging work. Spikes 5 and 6 need deployed infrastructure, so they run right after the CDK stack and before the orchestrator and Workflow_Client polling are wired. Pure logic (config, rules, state machine, store, approvals, notifier) comes next, then the Buyer runtime, infrastructure, Agent_Service, Listener, and CLI. The README, the CustomPiOS image, and the GitHub Action come last.

There is no mock store, S3 static site, or related-item browsing. Buyer interaction in tests uses Python-level fakes of the `WorkflowClient` only. Tests run without network access, AWS credentials, or a Nova Act API key.

## Tasks

- [ ] 1. Spike 1: user agent over CDP (runs first, gates Requirement 15)
  - [ ] 1.1 Write the spike 1 operator script `infra/spikes/spike1_user_agent_cdp.py`
    - Standalone script with its own pinned requirements note in the file header. It does not import the `ghostshopper` package, so it can run before the scaffold exists
    - Start an `aws.browser.v1` session, attach with Playwright and Nova Act over CDP, send `Target.setAutoAttach` (`waitForDebuggerOnStart`, `flatten`) and `Emulation.setUserAgentOverride` for every page target, and apply the override to existing pages
    - Read `navigator.userAgent` and check the `user-agent` header seen by a header-echo endpoint, for the first page, a popup, and a new tab. Exit non-zero if any value lacks `Agent/ghostshopper`
    - Write a pass or fail result with the observed values to `infra/spikes/results/spike1.md`
    - _Requirements: 15.2, 15.3, 15.4_

- [ ] 2. Checkpoint - Spike 1 gate
  - Run the spike with the user's AWS identity. If spike 1 fails, stop and ask the user, because the design says the project cannot meet Requirement 15 without another mechanism. Otherwise ensure all tests pass, ask the user if questions arise.

- [ ] 3. Project scaffold and shared common package
  - [ ] 3.1 Create the project scaffold and test tooling
    - `pyproject.toml` with extras `pi`, `buyer`, `dev`, the `undash` and listener entry points, and the `src/ghostshopper/` package layout from the design (`common`, `listener`, `agent`, `rules`, `notifier`, `buyer`, `config`, `cli`)
    - Configure `pytest`, `pytest-cov`, `hypothesis` (minimum 100 examples), `pytest-socket` with network disabled, `ruff`, and `mypy --strict` for `rules/` and `config/`
    - `tests/conftest.py` that fails a test that reads AWS or Nova Act environment variables
    - _Requirements: 20.7, 12.2_

  - [ ] 3.2 Implement `ghostshopper.common`
    - `USER_AGENT` (`ghostshopper/0.1 Agent/ghostshopper`), the `Clock` protocol with a system clock, and a `FakeClock` test helper that advances without sleeping
    - Money helpers (`Decimal` to integer cents and back) and MAC normalization to lowercase colon form
    - _Requirements: 15.1, 17.7_

  - [ ] 3.3 Implement the log redaction filter in `ghostshopper.common`
    - Redact values of `NTFY_ACCESS_TOKEN`, `NOVA_ACT_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and 43-character URL-safe strings
    - _Requirements: 12.7, 13.2_

  - [ ]* 3.4 Write property test for MAC normalization
    - **Property 26: MAC normalization**
    - **Validates: Requirements 17.6, 17.7**

- [ ] 4. AWS spikes 2 to 4 (before the Buyer runtime and packaging)
  - [ ] 4.1 Write the spike 2 script `infra/spikes/spike2_profile_start.py`
    - Start a session with `browser_session(..., profile_configuration={"profileIdentifier": ...})` in the pinned SDK version and check that the saved Amazon cookies are restored. Fall back to `start_browser_session(profileConfiguration=...)` plus a manual `BrowserClient` if the helper rejects the argument
    - Write the result to `infra/spikes/results/spike2.md`
    - _Requirements: 12.3, 13.4_

  - [ ] 4.2 Write the spike 3 script `infra/spikes/spike3_direct_code_package.py`
    - Build the arm64 zip with `uv pip install --python-platform aarch64-manylinux2014` for the `buyer` extra, report compressed and uncompressed sizes against the 250 MB and 750 MB limits, and check that Nova Act starts over CDP without a local Chrome install
    - Record the container-artifact fallback decision in `infra/spikes/results/spike3.md`
    - _Requirements: 12.1, 12.2_

  - [ ] 4.3 Write the spike 4 script `infra/spikes/spike4_verification_handoff.py`
    - Start a Buyer-owned session, print the region and session ID for console Live View, wait for the operator to take over and release control, and confirm that the Buyer's CDP connection reconnects
    - Write the result to `infra/spikes/results/spike4.md`
    - _Requirements: 14.1, 14.3, 14.4_

- [ ] 5. Checkpoint - Spikes 2 to 4 reviewed
  - Ensure all tests pass, ask the user if questions arise. Report any spike that failed and the chosen fallback before building dependent work.

- [ ] 6. Configuration models and loader
  - [ ] 6.1 Implement `ghostshopper.config`
    - Pydantic v2 models with `extra="forbid"`, `yaml.safe_load`, `dry_run` defaulting to true, ntfy settings, `buyer.*` fields, per-button fields including optional `debounce_seconds`, MAC normalization of keys, and duplicate-MAC rejection
    - Error output lists every invalid field path. Add `config.example.yaml` with no secret values
    - _Requirements: 8.7, 11.1, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7_

  - [ ]* 6.2 Write property test for config validation
    - **Property 25: Config validation**
    - **Validates: Requirements 8.7, 17.1, 17.2, 17.4, 17.5**

  - [ ]* 6.3 Write unit tests for config edge cases
    - Unknown keys such as `password` and `api_key`, duplicate MACs after case normalization, missing `dry_run` loads as true
    - _Requirements: 11.1, 17.3, 17.5, 17.6_

- [ ] 7. Order_Rules and State_Machine
  - [ ] 7.1 Implement `rules/decisions.py`
    - `decide_press`, `decide_quote`, `decide_substitute`, `decide_spend` as pure functions over `Decimal`, importing only `common/`, following the rule table
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 9.4_

  - [ ] 7.2 Implement `rules/state_machine.py`
    - `ALLOWED` with the 11 pairs, `TERMINAL`, `apply` raising `IllegalTransition`
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ]* 7.3 Write property test for press decision precedence
    - **Property 4: Press decision precedence**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

  - [ ]* 7.4 Write property test for quote decision
    - **Property 5: Quote decision**
    - **Validates: Requirements 4.5, 4.6, 4.7, 5.1**

  - [ ]* 7.5 Write property test for substitute decision
    - **Property 6: Substitute decision**
    - **Validates: Requirements 5.2, 5.3, 5.4**

  - [ ]* 7.6 Write property test for the state machine
    - **Property 9: State machine**
    - **Validates: Requirements 10.1, 10.2, 10.3**

  - [ ]* 7.7 Write pytest unit tests for each rule outcome and every transition
    - Cover in-flight ignore, Cooldown ignore, out of stock, over `max_price`, substitute proposal, `spend_cap` exceeded, and approval. Cover all 11 allowed and every disallowed pair
    - Run with `--cov=ghostshopper.rules --cov-fail-under=95`
    - _Requirements: 20.1, 20.2, 20.8_

- [ ] 8. Buyer wire schemas and Workflow_Client
  - [ ] 8.1 Implement `buyer/schemas.py`
    - `BuyerRequest`, `JobStatus`, `Quote`, `Substitute` (ASIN pattern `^[A-Z0-9]{10}$`), `PurchaseResult`, `approved_unit_price`, `dry_run`, and no field for a password, card number, or one-time code. No `nova_act` import
    - _Requirements: 4.3, 11.6, 13.1_

  - [ ] 8.2 Implement `buyer/client.py`
    - `WorkflowClient` protocol (`start`, `poll`), `AgentCoreWorkflowClient` using `boto3` `invoke_agent_runtime` with `runtimeSessionId = gs-<order_id_hex>-<action>`, the endpoint name as `qualifier`, `user_agent_extra` set from `USER_AGENT`, `BuyerUnavailable` on any boto3 or network error, and retry of `start(purchase)` on throttling only
    - Keep the polling contract consistent with the spike 4 findings. Revisit it after spike 6 (task 13.2) and adjust the limits in task 15.2 if the results differ
    - _Requirements: 12.4, 12.5, 12.6, 15.1_

  - [ ] 8.3 Add `FakeWorkflowClient` to `tests/fakes.py`
    - Scripts `JobStatus` sequences and raises `BuyerUnavailable`. No mock store of any kind
    - _Requirements: 20.6_

  - [ ]* 8.4 Write property test for Quote schema validation
    - **Property 22: Quote schema validation**
    - **Validates: Requirements 4.3, 4.4**

- [ ] 9. SQLite store, spend cap, approvals, restart recovery
  - [ ] 9.1 Implement `agent/store.py`
    - Schema from the design (`press_log`, `orders`, `order_history`, `approvals`, `meta`), WAL, `foreign_keys=ON`, `busy_timeout` of 5 seconds, indexes, and `Store.transition` that calls the State_Machine and writes the row and history entry in one transaction. An illegal transition is logged and returns `False`
    - _Requirements: 10.2, 10.4, 13.2_

  - [ ] 9.2 Implement the spend query and the atomic `approved` to `ordering` step in `agent/store.py`
    - `BEGIN IMMEDIATE`, sum of `placed` non-Dry_Run Orders for the current local day as UTC range, price times quantity, call `decide_spend`, then transition to `ordering` or `failed` / `spend_cap` in the same transaction. A lock timeout leaves the Order `approved` and logs
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.9, 9.10_

  - [ ] 9.3 Implement `agent/approvals.py`
    - `secrets.token_urlsafe(32)`, SHA-256 hash storage, 10-minute expiry, single-use acceptance in the same transaction as the Order transition, rejection reasons `unknown`, `used`, `expired`, `order_mismatch`, `bad_decision`, and the 5-second expiry sweeper
    - _Requirements: 6.6, 6.7, 6.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ] 9.4 Implement `agent/startup.py` restart recovery and environment checks
    - `ordering` to `failed` / `interrupted` with a "check the Amazon account" notification, `awaiting_approval` kept with its original `expires_at`, `pressed`, `quoted`, `approved` to `failed` / `interrupted`, terminal Orders untouched. Exit naming `NTFY_ACCESS_TOKEN` when unset
    - _Requirements: 8.8, 10.5, 10.6_

  - [ ]* 9.5 Write property test for the spend cap decision
    - **Property 8: Spend cap decision**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.9**

  - [ ]* 9.6 Write property test for transition persistence and restart recovery
    - **Property 10: Transition persistence and restart recovery**
    - **Validates: Requirements 10.4, 10.5, 10.6**

  - [ ]* 9.7 Write property test for the approval token lifecycle
    - **Property 11: Approval token lifecycle**
    - **Validates: Requirements 6.6, 6.7, 7.1, 7.2, 7.3, 7.7**

  - [ ]* 9.8 Write property test for invalid reply rejection
    - **Property 12: Invalid reply rejection**
    - **Validates: Requirements 7.4, 7.5, 7.6**

  - [ ]* 9.9 Write property and unit tests for approval expiry with `FakeClock`
    - **Property 13: Approval expiry**
    - Unit test the 10-minute boundary and the valid, unknown, used, and expired token cases
    - **Validates: Requirements 6.8, 20.3, 20.4**

  - [ ]* 9.10 Write the two-thread spend-cap atomicity test
    - Two threads attempt `approved` to `ordering` on one SQLite file and the check and transition stay serialized
    - _Requirements: 9.10_

- [ ] 10. Notifier and ntfy stream
  - [ ] 10.1 Implement `notifier/`
    - ntfy JSON publish with `Authorization` and `User-Agent` headers, retry 3 times at 2-second spacing, approval message text, Substitute marker, Approve and Deny `http` actions with JSON body, reply parser, terminal-state notices, and the verification notice that names region and browser session ID and never contains a Live View URL
    - _Requirements: 5.5, 6.2, 6.3, 6.4, 6.5, 6.9, 8.3, 14.2_

  - [ ] 10.2 Implement `agent/ntfy_stream.py`
    - `httpx` streaming `GET {ntfy_url}/{reply_topic}/json?since=<last_id>`, first run `since=latest`, last ID stored in `meta`, backoff `min(1 * 2^n, 60)` seconds with reset after a message, each disconnect logged
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 10.3 Write property test for notification rendering and action round trip
    - **Property 14: Notification rendering and action round trip**
    - **Validates: Requirements 5.5, 6.2, 6.3, 6.4, 6.5**

  - [ ]* 10.4 Write property test for ntfy reconnect backoff and resume
    - **Property 16: ntfy reconnect backoff and resume**
    - **Validates: Requirements 8.4, 8.5**

- [ ] 11. Buyer runtime (cloud side only)
  - [ ] 11.1 Implement `buyer/runtime/guards.py` and the user agent gate
    - Pure `is_reverification(url, dom)` over sign-in, MFA, CAPTCHA routes and password, one-time-code, CAPTCHA, and card-number inputs. Pure `verify_user_agent(observed)`
    - _Requirements: 13.3, 14.1, 15.3, 15.4_

  - [ ] 11.2 Implement browser session and CDP handling in `buyer/runtime/`
    - Context manager that starts a session from the Browser_Profile, attaches `NovaAct(cdp_endpoint_url=..., cdp_headers=...)`, applies `Target.setAutoAttach` and `Emulation.setUserAgentOverride` using the mechanism confirmed by spike 1, runs the `navigator.userAgent` gate before any navigation, listens on `context.on("request")` for requests without the token, and always stops the session exactly once
    - _Requirements: 12.2, 12.3, 12.8, 15.2, 15.3, 15.4_

  - [ ] 11.3 Implement the `quote`, `substitute`, and `purchase` flows
    - Fixed preamble that states the actor is an automated agent and never to enter a password, card number, or one-time code. `act_get` with Pydantic schemas, guard runs between steps, `price_changed` check, stop before Place Order when `dry_run` is true, Buy Now only, no added delays. Verification wait for up to 10 minutes that tolerates CDP reconnects, and profile save only after a cleared prompt
    - _Requirements: 4.3, 5.1, 5.6, 9.6, 11.2, 11.6, 13.3, 14.1, 14.3, 14.4, 14.6, 15.5, 15.6_

  - [ ] 11.4 Implement the runtime entry point and bootstrap
    - Non-blocking `@app.entrypoint` with `add_async_task`, an in-memory job table keyed by `order_id + action`, idempotent start, `status` action, Secrets Manager bootstrap of `NOVA_ACT_API_KEY`, and log redaction installed at start
    - _Requirements: 12.1, 12.7, 14.3_

  - [ ]* 11.5 Write property test for the user agent gate
    - **Property 20: User agent gate**
    - **Validates: Requirements 15.3, 15.4**

  - [ ]* 11.6 Write property test for reverification detection
    - **Property 21: Reverification detection**
    - **Validates: Requirements 13.3, 14.1**

  - [ ]* 11.7 Write property test for browser session cleanup
    - **Property 29: Browser session cleanup**
    - **Validates: Requirements 12.8**

  - [ ]* 11.8 Write unit tests for the flow driver over a fake page
    - Assert no Place Order action is issued when `dry_run` is true and that no `nova_act` import is needed
    - _Requirements: 11.2, 20.6_

- [ ] 12. Infrastructure (CDK in Python, L1 constructs)
  - [ ] 12.1 Write the Buyer zip build script `infra/build_buyer.sh`
    - Uses the packaging approach confirmed by spike 3 and zips the `buyer` extra for arm64
    - _Requirements: 22.1_

  - [ ] 12.2 Implement the CDK stack in `infra/`
    - `Asset`, Secrets Manager secret (empty), Buyer execution role with the permissions from the design, `CfnRuntime` (IAM inbound auth, `PYTHON_3_13`, lifecycle 300 and 3600), `CfnRuntimeEndpoint` named `ghostshopper_live`, `CfnBrowserProfile` named `ghostshopper_amazon`, and the Invoke user with one `InvokeAgentRuntime` statement on the runtime ARN and the runtime-endpoint ARN. No access keys are created. Outputs feed `config.yaml`
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

  - [ ] 12.3 Implement `infra/tools/login_session.py`
    - Runs under the operator's own identity, starts a session from the profile, prints a presigned Live View URL (300-second maximum) to the terminal only, waits for the user to sign in, calls `save_browser_session_profile`, and stops the session. It never handles the Amazon password
    - _Requirements: 13.4, 13.5, 22.7_

  - [ ]* 12.4 Write CDK assertion tests
    - Policy statements, no wildcard resources, no profile management or `StartBrowserSession` for the Invoke identity, profile ID wired into the Buyer role. No property tests
    - _Requirements: 22.2, 22.4, 22.5_

- [ ] 13. AWS spikes 5 and 6 (need the deployed stack)
  - [ ] 13.1 Write the spike 5 script `infra/spikes/spike5_iam_check.py`
    - `simulate-principal-policy` for the Invoke identity: `DEFAULT` endpoint (deny), another runtime (deny), `StartBrowserSession` (deny), named endpoint (allow), then one real invoke using only the two ARNs
    - _Requirements: 22.2, 22.4_

  - [ ] 13.2 Write the spike 6 script `infra/spikes/spike6_async_job.py`
    - Confirm a session that reports `HealthyBusy` survives a 12-minute job and that a status call on the same `runtimeSessionId` returns the job
    - _Requirements: 12.1, 14.3_

- [ ] 14. Checkpoint - Infrastructure and spikes complete
  - Ensure all tests pass, ask the user if questions arise. Report the results of spikes 5 and 6 and adjust the polling limits if they differ from the design.

- [ ] 15. Agent_Service: status page, orchestrator, wiring
  - [ ] 15.1 Implement `agent/app.py` routes and the Status_Page
    - `POST /internal/press` (loopback client only), `GET /`, `GET /events` (SSE with `Hub.publish`), `GET /api/state`. Page model selects no token hash, raw token, or secret. Dry-run banner and "dry run" label
    - _Requirements: 3.5, 3.7, 8.2, 11.4, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_

  - [ ] 15.2 Implement `agent/orchestrator.py`
    - One asyncio task per Order, `asyncio.to_thread` for client calls, 5-second polling with 6 tolerated errors, job limits of 300 and 900 seconds (extended by up to 600 after `verification_required`), result mapping table, substitute path, approval flow, atomic spend-cap step, purchase request with `asin` (the Substitute ASIN when `is_substitute`), `dry_run`, and `approved_unit_price`, and one notification per terminal failure
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 5.1, 5.6, 6.1, 6.9, 9.5, 9.7, 9.8, 11.3, 11.5, 11.6, 12.4, 12.6, 14.2, 14.5_

  - [ ] 15.3 Wire the service entry point `agent/main.py`
    - Load config, run startup checks and recovery, start the ntfy stream, the expiry sweeper, the orchestrator, and the FastAPI app listening on the LAN address
    - _Requirements: 8.1, 8.8, 10.5, 10.6_

  - [ ]* 15.4 Write property test for Buyer result mapping
    - **Property 17: Buyer result mapping**
    - **Validates: Requirements 4.4, 9.5, 9.7, 9.8, 12.6, 14.5, 15.4**

  - [ ]* 15.5 Write property tests for purchase ASIN selection and dry-run handling
    - **Property 7: Purchase ASIN selection**
    - **Property 18: Dry-run handling**
    - **Validates: Requirements 5.6, 11.1, 11.3, 11.5, 11.6**

  - [ ]* 15.6 Write property test for terminal-state notification
    - **Property 15: Terminal-state notification**
    - **Validates: Requirements 6.9**

  - [ ]* 15.7 Write property test for status page content
    - **Property 24: Status page content**
    - **Validates: Requirements 11.4, 16.1, 16.2, 16.4, 16.5**

  - [ ]* 15.8 Write an SSE latency example test
    - A state change reaches a connected client within 2 seconds
    - _Requirements: 16.3_

- [ ] 16. Listener
  - [ ] 16.1 Implement the classifier and debouncer in `listener/`
    - `classify(packet)` for ARP probes (sender IP `0.0.0.0`) and DHCP Requests with filter `arp or (udp and (port 67 or 68))`, and `Debouncer` driven by the packet timestamp with a 30-second default and per-MAC windows. scapy is imported only here
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 16.2 Implement event delivery and pcap mode
    - In-memory queue and worker thread that POSTs to `http://127.0.0.1:<port>/internal/press` with `httpx`, `USER_AGENT` header, 3 retries at 5 seconds, drop and log, non-blocking sniff loop, and pcap mode that drains the queue and exits 0
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ] 16.3 Create the pcap fixture generator and `tests/fixtures/dash_press.pcap`
    - Deterministic script using scapy that writes ARP probe bursts, a DHCP request, and noise from two MACs
    - _Requirements: 20.5_

  - [ ]* 16.4 Write property test for press classification
    - **Property 1: Press classification**
    - **Validates: Requirements 1.1**

  - [ ]* 16.5 Write property test and pcap-based tests for debounce
    - **Property 3: Debounce**
    - Replay `dash_press.pcap` through the classifier and debouncer and assert the accepted presses per MAC
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 20.5**

  - [ ]* 16.6 Write property test for press delivery retry schedule
    - **Property 2: Press delivery retry schedule**
    - **Validates: Requirements 1.5, 1.6**

  - [ ]* 16.7 Write pcap-mode unit tests for the Listener process
    - Reading the fixture posts the expected events to a local test server on loopback, then exits with status 0
    - _Requirements: 1.3, 1.4, 20.5_

- [ ] 17. CLI (`undash`)
  - [ ] 17.1 Implement `undash setup`
    - GET `http://192.168.0.1/` with `amzn_ssid` and `amzn_pw` encoded through `urllib.parse.urlencode(quote_via=quote)`, 10-second timeout, `USER_AGENT` header, prints serial number, MAC, firmware version, and battery level, non-zero exit when unreachable, password from prompt or `--password-stdin`, never written to a file or log
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

  - [ ] 17.2 Implement `undash discover`
    - Group `press_log` rows with `outcome = unconfigured` by MAC with count and latest time, `--pcap FILE` using the Listener classifier, and the "no unconfigured buttons were seen" message
    - _Requirements: 19.1, 19.2, 19.3, 19.4_

  - [ ]* 17.3 Write property test for setup request encoding
    - **Property 27: Setup request encoding**
    - **Validates: Requirements 18.1, 18.2**

  - [ ]* 17.4 Write property test for discovery listing
    - **Property 28: Discovery listing**
    - **Validates: Requirements 19.1, 19.2, 19.3**

- [ ] 18. Cross-cutting tests
  - [ ]* 18.1 Write property test for secret non-disclosure
    - **Property 23: Secret non-disclosure**
    - **Validates: Requirements 7.7, 12.7, 13.1, 13.2, 16.6, 17.3, 18.5**

  - [ ]* 18.2 Write property test for the user agent on every outbound request
    - **Property 19: User agent on every outbound request**
    - **Validates: Requirements 1.7, 8.3, 15.1, 18.6**

- [ ] 19. Checkpoint - Application complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 20. README
  - [ ] 20.1 Write `README.md`
    - Hardware and network setup with `undash setup`, blocking buttons at the Router, the note that some buttons hardcode DNS `1.1.1.1`, environment variable list (`NOVA_ACT_API_KEY` via Secrets Manager bootstrap, `NTFY_ACCESS_TOKEN`, AWS credentials), CDK deploy steps and Invoke_Credential key creation, the one-time login through `infra/tools/login_session.py`, the dry-run default and how to set `dry_run: false`, how GhostShopper follows the Agent_Terms, the `simulate-principal-policy` check, the unauthenticated Status_Page note, and the concurrent-approval risk
    - _Requirements: 13.5, 15.7, 22.6, 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7_

  - [ ]* 20.2 Write a README heading and content check
    - Test that the required sections and statements exist
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7_

- [ ] 21. CustomPiOS image
  - [ ] 21.1 Create the CustomPiOS module in `image/`
    - Installs the `pi` extra into a virtualenv, creates the `ghostshopper` system user, and installs `config.example.yaml`. No Nova Act, Playwright, or Chrome
    - _Requirements: 21.1, 21.6_

  - [ ] 21.2 Add the systemd units and env template
    - Listener unit with `AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN`, unprivileged Agent_Service unit with `EnvironmentFile=/etc/ghostshopper/env`, an empty env file template with no secret values, and both units enabled
    - _Requirements: 21.1, 21.6_

- [ ] 22. GitHub Action for the Pi image
  - [ ] 22.1 Write `.github/workflows/image.yml`
    - Triggers: `workflow_dispatch` and `push: tags: ['v*']` only, no branch push. Build with the CustomPiOS GitHub Action, upload with `actions/upload-artifact`, and on a tag run attach the image to the matching GitHub release. No secret is passed into the image build
    - _Requirements: 21.2, 21.3, 21.4, 21.5, 21.6_

  - [ ]* 22.2 Write a workflow YAML check
    - Assert the triggers, the absence of an ordinary push trigger, the artifact step, and the release step on tags
    - _Requirements: 21.2, 21.3, 21.4, 21.5_

- [ ] 23. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. The optional tests carry the pytest coverage required by Requirement 20, including the 95 percent line coverage gate on `rules/` in task 7.7.
- Spike 1 (task 1) runs before everything else. Spikes 2 to 4 run before the Buyer runtime and packaging. Spikes 5 and 6 need the deployed stack and run before the orchestrator is wired.
- The spike tasks write scripts and result files only. Running them needs the user's AWS identity, and a failed spike pauses the plan at the next checkpoint.
- There is no mock store or S3 site. Buyer tests use `FakeWorkflowClient` and a fake page only.
- Each task references specific requirements for traceability. Property tests validate universal correctness properties. Unit tests validate examples and edge cases.
- The README and the image and workflow tasks come last, as requested.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3"] },
    { "id": 4, "tasks": ["3.4", "4.1", "4.2"] },
    { "id": 5, "tasks": ["4.3"] },
    { "id": 6, "tasks": ["5"] },
    { "id": 7, "tasks": ["6.1", "8.1"] },
    { "id": 8, "tasks": ["6.2", "6.3", "7.1", "7.2", "8.2", "8.4", "11.1", "12.1", "12.3"] },
    { "id": 9, "tasks": ["7.3", "7.4", "7.5", "7.6", "7.7", "8.3", "10.1", "11.2", "11.5", "11.6"] },
    { "id": 10, "tasks": ["9.1", "10.3", "11.3", "11.7"] },
    { "id": 11, "tasks": ["9.2", "9.3", "10.2", "11.4", "11.8"] },
    { "id": 12, "tasks": ["9.4", "9.5", "9.7", "9.8", "9.9", "9.10", "10.4", "12.2"] },
    { "id": 13, "tasks": ["9.6", "12.4", "13.1", "13.2"] },
    { "id": 14, "tasks": ["14"] },
    { "id": 15, "tasks": ["15.1", "16.1", "16.3", "17.1"] },
    { "id": 16, "tasks": ["15.2", "15.7", "16.2", "16.4", "16.5", "17.2", "17.3"] },
    { "id": 17, "tasks": ["15.3", "15.4", "15.5", "15.6", "15.8", "16.6", "16.7", "17.4"] },
    { "id": 18, "tasks": ["18.1", "18.2"] },
    { "id": 19, "tasks": ["19"] },
    { "id": 20, "tasks": ["20.1"] },
    { "id": 21, "tasks": ["20.2", "21.1"] },
    { "id": 22, "tasks": ["21.2"] },
    { "id": 23, "tasks": ["22.1"] },
    { "id": 24, "tasks": ["22.2"] },
    { "id": 25, "tasks": ["23"] }
  ]
}
```
