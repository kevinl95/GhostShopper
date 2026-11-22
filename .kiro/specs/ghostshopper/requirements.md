# Requirements Document

## Introduction

GhostShopper revives retired Amazon Dash buttons. A Raspberry Pi detects a button press, an agent service applies deterministic order rules, a Nova Act workflow on AWS AgentCore Runtime reads the product page and performs Buy Now in an AgentCore Browser session, and the user approves each purchase through an ntfy notification. The Pi image contains the listener and the agent service only. No x86 host, local Chrome, or Playwright is used.

Out of scope: any mock store, S3 static site, or related-item browsing. Buyer tests use Python-level fakes of the workflow client.

## Glossary

- **GhostShopper**: The complete system described in this document.
- **Listener**: The Python process on the Raspberry Pi that sniffs ARP and DHCP traffic and detects Dash button presses.
- **Agent_Service**: The Python 3.10+ FastAPI process on the Raspberry Pi that owns order state, order rules, the SQLite database, the ntfy subscriber, and the Status_Page.
- **Order_Rules**: The plain-Python module, free of model calls and network I/O, that decides whether a press becomes a purchase attempt.
- **State_Machine**: The plain-Python module that defines legal Order_State transitions.
- **Buyer**: The Nova Act workflow deployed to AgentCore_Runtime that reads product data and performs Buy Now in an AgentCore_Browser session.
- **Workflow_Client**: The Python interface the Agent_Service uses to invoke the Buyer. Tests replace the Workflow_Client with fakes.
- **Notifier**: The component that publishes notifications to the ntfy server.
- **CLI**: The `undash` command-line tool.
- **Status_Page**: The web page served by the Agent_Service that shows button presses and orders.
- **Config_File**: The YAML configuration file.
- **Button**: A physical Dash button identified by its MAC address in the Config_File.
- **Unconfigured_MAC**: A MAC address that appears in a press event and has no entry in the Config_File.
- **Press_Event**: A record of one detected button press, containing the MAC address and a UTC timestamp.
- **Debounce_Window**: The per-button interval after an accepted press during which the Listener drops further presses of the same Button. The default is 30 seconds.
- **Order**: A purchase attempt created from an accepted Press_Event.
- **Order_State**: One of pressed, quoted, awaiting_approval, approved, ordering, placed, denied, expired, failed.
- **In_Flight_Order**: An Order in state pressed, quoted, awaiting_approval, approved, or ordering.
- **Cooldown**: The period of cooldown_days after the most recent real Order in state placed for a Button, during which new presses of that Button are ignored.
- **Dry_Run**: A mode in which the Buyer stops before the final Place Order click and no purchase occurs.
- **Daily_Spend_Cap**: The configured maximum total price of Orders in state placed within one calendar day in the Agent_Service time zone.
- **Quote**: The structured product data returned by the Buyer: title, price, availability, and delivery estimate.
- **Substitute**: One alternative product proposed by the Buyer when allow_substitutes is true for the Button.
- **Approval_Token**: A single-use random value bound to one Order, valid for 10 minutes.
- **Reply_Topic**: The ntfy topic to which action buttons post approval decisions.
- **Notification_Topic**: The ntfy topic to which the Notifier publishes notifications.
- **ntfy_Access_Token**: The ntfy access token read from an environment variable and used on both topics.
- **AgentCore_Runtime**: Amazon Bedrock AgentCore Runtime, the hosting service for the Buyer.
- **AgentCore_Browser**: The managed cloud browser of Amazon Bedrock AgentCore.
- **Browser_Profile**: An AgentCore_Browser profile resource that stores the Amazon login cookies and local storage.
- **Live_View**: The AgentCore_Browser streamed view that lets the user interact with a running browser session.
- **Reverification_Prompt**: An Amazon page that asks the user to verify identity again, including a password, one-time code, or CAPTCHA.
- **Invoke_Credential**: The IAM credential the Agent_Service uses to call the Buyer endpoint.
- **IaC_Stack**: The infrastructure-as-code definition that provisions AWS resources.
- **Image_Workflow**: The GitHub Actions workflow that builds the Raspberry Pi image with CustomPiOS.
- **Agent_User_Agent**: A user agent string that includes the token `Agent/ghostshopper`.
- **Agent_Terms**: The Agent Terms section of the Amazon Conditions of Use.
- **Router**: The home network router on which the user blocks Dash buttons from the internet.

## Requirements

### Requirement 1: Press Detection

**User Story:** As a home user, I want the Pi to detect presses of my Dash buttons, so that a press can start a reorder.

#### Acceptance Criteria

1. WHEN the Listener observes an ARP or DHCP packet that matches the Dash press signature, THE Listener SHALL create a Press_Event containing the source MAC address and the UTC timestamp.
2. WHEN the Listener creates a Press_Event, THE Listener SHALL send the Press_Event to the Agent_Service by HTTP POST.
3. WHERE a pcap file path is supplied, THE Listener SHALL read packets from the pcap file instead of a live network interface.
4. WHEN the Listener finishes reading a pcap file, THE Listener SHALL exit with status code 0.
5. IF the Agent_Service does not return a 2xx response to a Press_Event POST, THEN THE Listener SHALL retry the POST up to 3 times at 5-second intervals and log each failure.
6. IF all retries of a Press_Event POST fail, THEN THE Listener SHALL log the dropped Press_Event and continue sniffing.
7. THE Listener SHALL send the Agent_User_Agent in every HTTP request.

### Requirement 2: Per-Button Debounce

**User Story:** As a home user, I want one physical press to cause one order attempt, so that button bounce does not trigger duplicates.

#### Acceptance Criteria

1. WHEN the Listener accepts a Press_Event for a MAC address, THE Listener SHALL start a Debounce_Window for that MAC address.
2. WHILE a Debounce_Window is active for a MAC address, THE Listener SHALL drop further Press_Events from that MAC address.
3. THE Listener SHALL use a Debounce_Window of 30 seconds when the Config_File sets no debounce value for the Button.
4. WHERE the Config_File sets a debounce value for a Button, THE Listener SHALL use that value as the Debounce_Window for that Button.
5. THE Listener SHALL track Debounce_Windows independently for each MAC address.

### Requirement 3: Deterministic Order Rules

**User Story:** As a home user, I want the rules that spend my money to be plain code, so that a model cannot decide to buy.

#### Acceptance Criteria

1. THE Order_Rules SHALL decide every accept, ignore, notify-only, and purchase outcome without calling any model.
2. WHEN the Agent_Service receives a Press_Event for a Button that has an In_Flight_Order, THE Agent_Service SHALL ignore the press and create no Order.
3. WHILE a Button is in Cooldown, THE Agent_Service SHALL ignore presses of that Button and create no Order.
4. WHEN the Agent_Service receives a Press_Event for a Button that is neither in flight nor in Cooldown, THE Agent_Service SHALL create an Order in state pressed.
5. WHEN the Agent_Service receives a Press_Event for an Unconfigured_MAC, THE Agent_Service SHALL record the Press_Event for the Status_Page and discovery, and SHALL create no Order.
6. THE Agent_Service SHALL exclude Orders created in Dry_Run from Cooldown calculations.
7. WHEN the Agent_Service ignores a press, THE Agent_Service SHALL record the reason (in_flight, cooldown, or unconfigured) in the press log.

### Requirement 4: Product Quote

**User Story:** As a home user, I want to see the real price and availability before I approve, so that I do not buy something unexpected.

#### Acceptance Criteria

1. WHEN an Order enters state pressed, THE Agent_Service SHALL request a Quote for the configured ASIN from the Buyer through the Workflow_Client.
2. WHEN the Buyer returns a Quote, THE Agent_Service SHALL move the Order to state quoted.
3. THE Buyer SHALL return the Quote as a Pydantic-validated object with the fields title, price, availability, and delivery estimate, obtained through Nova Act `act_get`.
4. IF the Quote does not validate against the Pydantic schema, THEN THE Agent_Service SHALL move the Order to state failed with reason invalid_quote and send a notification.
5. IF the Quote shows the product as out of stock and allow_substitutes is false, THEN THE Agent_Service SHALL move the Order to state failed with reason out_of_stock, send a notification, and request no purchase.
6. IF the Quote price exceeds the max_price of the Button and allow_substitutes is false, THEN THE Agent_Service SHALL move the Order to state failed with reason over_max_price, send a notification, and request no purchase.
7. THE Agent_Service SHALL apply the out_of_stock and over_max_price decisions in the Order_Rules, using the Quote values and no model judgment.

### Requirement 5: Substitute Proposal

**User Story:** As a home user, I want to allow one substitute when my product is unavailable, so that I still get what I need while keeping control.

#### Acceptance Criteria

1. WHERE allow_substitutes is true for a Button and the Quote shows the product as out of stock or above max_price, THE Buyer SHALL propose at most one Substitute.
2. WHEN the Buyer proposes a Substitute, THE Agent_Service SHALL require approval of the Substitute regardless of any other setting.
3. IF the Substitute price exceeds the max_price of the Button, THEN THE Agent_Service SHALL move the Order to state failed with reason over_max_price, send a notification, and request no purchase.
4. WHERE allow_substitutes is true and the Buyer proposes no Substitute, THE Agent_Service SHALL move the Order to state failed with reason no_substitute and send a notification.
5. WHEN the Agent_Service sends an approval request for a Substitute, THE Notifier SHALL state the Substitute title, price, and delivery date and mark the message as a substitute.
6. WHEN an approved Order refers to a Substitute, THE Buyer SHALL purchase the Substitute ASIN and not the configured ASIN.

### Requirement 6: Approval Through ntfy

**User Story:** As a home user, I want to approve or deny every purchase from my phone, so that nothing is bought without my consent.

#### Acceptance Criteria

1. WHEN an Order is in state quoted and passes the Order_Rules, THE Agent_Service SHALL create an Approval_Token, move the Order to state awaiting_approval, and publish a notification to the Notification_Topic.
2. THE Notifier SHALL word the approval notification as "<product> is $X, arriving <date>. Approve?" with the product title, price, and delivery date filled in.
3. THE Notifier SHALL attach an Approve action button and a Deny action button to the approval notification.
4. THE Notifier SHALL configure each action button to POST a JSON body containing order_id, token, and decision (approve or deny) to the Reply_Topic on the ntfy server.
5. THE Notifier SHALL pass the ntfy_Access_Token as a header on each action button.
6. WHEN the Agent_Service receives a valid approve reply within 10 minutes of the notification, THE Agent_Service SHALL move the Order to state approved.
7. WHEN the Agent_Service receives a valid deny reply, THE Agent_Service SHALL move the Order to state denied.
8. IF 10 minutes pass after the notification without a valid reply, THEN THE Agent_Service SHALL move the Order to state expired and treat the outcome as a deny.
9. WHEN an Order reaches state denied, expired, or failed, THE Notifier SHALL publish a notification stating the final state and reason.

### Requirement 7: Approval Token Security

**User Story:** As a home user, I want approval replies to be authentic and single-use, so that nobody else can approve a purchase.

#### Acceptance Criteria

1. WHEN the Agent_Service creates an Order approval, THE Agent_Service SHALL generate an Approval_Token from a cryptographically secure random source.
2. THE Agent_Service SHALL accept each Approval_Token for exactly one reply.
3. THE Agent_Service SHALL treat an Approval_Token as expired 10 minutes after creation.
4. IF a reply contains an unknown, used, or expired Approval_Token, THEN THE Agent_Service SHALL ignore the reply and write a log entry containing the order_id and the rejection reason.
5. IF a reply does not match the order_id bound to the Approval_Token, THEN THE Agent_Service SHALL ignore the reply and write a log entry.
6. IF a reply carries a decision other than approve or deny, THEN THE Agent_Service SHALL ignore the reply and write a log entry.
7. THE Agent_Service SHALL store only a hash of each Approval_Token in the SQLite database.

### Requirement 8: Outbound ntfy Subscription

**User Story:** As a home user, I want the Pi to receive my replies without opening my home network, so that the setup stays safe.

#### Acceptance Criteria

1. THE Agent_Service SHALL subscribe to the Reply_Topic through an outbound ntfy JSON stream.
2. THE Agent_Service SHALL listen on no inbound reachability path beyond the local network, and SHALL require no tunnel or public callback URL.
3. THE Agent_Service SHALL send the ntfy_Access_Token as a header on the stream request and on every publish request.
4. IF the ntfy stream disconnects, THEN THE Agent_Service SHALL reconnect with exponential backoff capped at 60 seconds and log each disconnect.
5. WHEN the ntfy stream reconnects, THE Agent_Service SHALL resume from the last processed message identifier.
6. THE Agent_Service SHALL read the ntfy_Access_Token from an environment variable.
7. THE Config_File SHALL define the ntfy server URL, the Notification_Topic, and the Reply_Topic.
8. IF the ntfy_Access_Token environment variable is unset at startup, THEN THE Agent_Service SHALL exit with a message that names the variable.

### Requirement 9: Purchase and Spend Cap

**User Story:** As a home user, I want purchases to use Buy Now and respect my spending limit, so that orders are simple and bounded.

#### Acceptance Criteria

1. WHEN an Order enters state approved, THE Agent_Service SHALL evaluate the Daily_Spend_Cap before requesting the purchase.
2. THE Agent_Service SHALL compute spend for the Daily_Spend_Cap as the sum of prices of Orders in state placed within the current day, excluding Dry_Run Orders.
3. THE Agent_Service SHALL exclude Orders in states approved and ordering from the Daily_Spend_Cap sum.
4. IF the sum of placed spend plus the Order price exceeds the Daily_Spend_Cap, THEN THE Agent_Service SHALL move the Order to state failed with reason spend_cap and send a notification.
5. WHEN the Daily_Spend_Cap check passes, THE Agent_Service SHALL move the Order to state ordering and request the purchase from the Buyer.
6. WHEN the Buyer completes a purchase, THE Buyer SHALL use the Amazon Buy Now button and return the order number.
7. WHEN the Buyer returns an order number, THE Agent_Service SHALL store the order number, move the Order to state placed, and send a confirmation notification.
8. IF the Buyer reports a purchase error, THEN THE Agent_Service SHALL move the Order to state failed with the error reason and send a notification.
9. THE Agent_Service SHALL evaluate the Daily_Spend_Cap before every purchase, including purchases of Substitutes.
10. THE Agent_Service SHALL run the spend-cap check and the transition to ordering as one atomic SQLite transaction.

### Requirement 10: Order State Machine

**User Story:** As a maintainer, I want a strict order state machine, so that illegal state changes are impossible.

#### Acceptance Criteria

1. THE State_Machine SHALL allow only these transitions: pressed to quoted, pressed to failed, quoted to awaiting_approval, quoted to failed, awaiting_approval to approved, awaiting_approval to denied, awaiting_approval to expired, approved to ordering, approved to failed, ordering to placed, and ordering to failed.
2. IF a transition outside the allowed set is requested, THEN THE State_Machine SHALL reject the transition, leave the Order state unchanged, and log the rejected transition.
3. THE State_Machine SHALL treat placed, denied, expired, and failed as terminal states.
4. WHEN the State_Machine accepts a transition, THE Agent_Service SHALL persist the new state with a UTC timestamp in the SQLite database.
5. WHEN the Agent_Service starts, THE Agent_Service SHALL move each Order found in state ordering to state failed with reason interrupted and send a notification asking the user to check the Amazon account.
6. WHEN the Agent_Service starts, THE Agent_Service SHALL keep each Order in state awaiting_approval and keep its Approval_Token valid until the original 10-minute expiry.

### Requirement 11: Dry Run

**User Story:** As a home user, I want to try the whole flow without spending money, so that I can trust it before going live.

#### Acceptance Criteria

1. THE Config_File SHALL default dry_run to true.
2. WHILE dry_run is true, THE Buyer SHALL stop before the final Place Order click.
3. WHEN a Dry_Run Order reaches the end of the Buyer flow, THE Agent_Service SHALL move the Order to state placed, mark the Order as dry_run, and record no order number.
4. THE Status_Page SHALL label every Dry_Run Order as dry run.
5. WHERE the Config_File sets dry_run to false, THE Agent_Service SHALL request real purchases.
6. THE Agent_Service SHALL send the dry_run value to the Buyer with each purchase request, and the Buyer SHALL use the value from the request.

### Requirement 12: Cloud Buyer and Browser Profile

**User Story:** As a home user, I want the buyer to run in the cloud with my saved Amazon login, so that no local browser or credential handling is needed.

#### Acceptance Criteria

1. THE Buyer SHALL run as a Nova Act workflow deployed to AgentCore_Runtime.
2. THE Buyer SHALL drive an AgentCore_Browser session and SHALL use no local Chrome, Playwright installation, or user_data_dir.
3. WHEN the Buyer starts a browser session, THE Buyer SHALL start the session from the configured Browser_Profile.
4. THE Agent_Service SHALL call the Buyer only through the Workflow_Client interface.
5. THE Agent_Service SHALL authenticate to the Buyer endpoint with the Invoke_Credential.
6. IF the Buyer endpoint is unreachable or returns an error, THEN THE Agent_Service SHALL move the Order to state failed with reason buyer_unavailable and send a notification.
7. THE Buyer SHALL read the Nova Act API key from an environment variable and SHALL not write the key to logs.
8. WHEN the Buyer ends a session, THE Buyer SHALL close the AgentCore_Browser session.

### Requirement 13: Credential Isolation

**User Story:** As a home user, I want the buyer never to touch my password or card number, so that my credentials stay safe.

#### Acceptance Criteria

1. THE Buyer SHALL receive no Amazon password, card number, or one-time code in any input, prompt, log, or return value.
2. THE Agent_Service SHALL store no Amazon password, card number, or one-time code in the SQLite database, Config_File, or logs.
3. WHEN the Amazon page shows a password, card number, or one-time code entry field, THE Buyer SHALL stop entering data on that page and handle the page as a Reverification_Prompt.
4. THE Buyer SHALL authenticate to Amazon only through cookies and local storage restored from the Browser_Profile.
5. THE README SHALL instruct the user to log in once through Live View and save the session to the Browser_Profile.

### Requirement 14: Amazon Re-Verification

**User Story:** As a home user, I want to complete Amazon re-verification myself, so that the buyer never handles verification secrets.

#### Acceptance Criteria

1. WHEN the Buyer detects a Reverification_Prompt, THE Buyer SHALL pause the purchase flow and report a verification_required status to the Agent_Service.
2. WHEN the Agent_Service receives verification_required, THE Notifier SHALL publish a notification that asks the user to complete verification in Live View.
3. WHILE the Buyer waits for verification, THE Buyer SHALL keep the AgentCore_Browser session open for up to 10 minutes.
4. WHEN the Reverification_Prompt clears within 10 minutes, THE Buyer SHALL resume the purchase flow.
5. IF the Reverification_Prompt does not clear within 10 minutes, THEN THE Agent_Service SHALL move the Order to state failed with reason verification_timeout and send a notification.
6. THE Buyer SHALL NOT solve, bypass, or circumvent any CAPTCHA or other human-verification measure.

### Requirement 15: Agent Identification

**User Story:** As a user who respects Amazon's rules, I want the system to identify itself as an agent, so that GhostShopper follows the Agent_Terms.

#### Acceptance Criteria

1. THE Agent_Service SHALL send the Agent_User_Agent in every outbound HTTP request, including ntfy requests and Workflow_Client requests.
2. THE Buyer SHALL apply the Agent_User_Agent to every AgentCore_Browser session before the first navigation.
3. WHEN the Buyer starts a browser session, THE Buyer SHALL read navigator.userAgent from the page and confirm that the value contains `Agent/ghostshopper`.
4. IF the observed user agent lacks `Agent/ghostshopper`, THEN THE Buyer SHALL stop the session before navigating to Amazon and report an error that the Agent_Service records as reason user_agent_unverified.
5. THE Buyer SHALL perform page interaction at the pace Nova Act produces and SHALL add no delay or input pattern intended to imitate human behavior.
6. WHEN a person or Amazon page asks whether the actor is a human, THE Buyer SHALL answer that the actor is an automated agent.
7. THE README SHALL describe how GhostShopper meets each rule of the Agent_Terms.

### Requirement 16: Status Page

**User Story:** As a home user, I want a status page, so that I can see presses and orders as they happen.

#### Acceptance Criteria

1. THE Status_Page SHALL show a list of recent Press_Events with MAC address, timestamp, and outcome.
2. THE Status_Page SHALL show a list of Orders with Button name, product name, Order_State, price, order number, and timestamps.
3. WHEN a Press_Event arrives or an Order changes state, THE Status_Page SHALL update within 2 seconds without a manual reload.
4. THE Status_Page SHALL show the current spend total toward the Daily_Spend_Cap.
5. THE Status_Page SHALL show a dry-run indicator when dry_run is true.
6. THE Status_Page SHALL show no Approval_Token and no secret value.

### Requirement 17: YAML Configuration

**User Story:** As a home user, I want to configure buttons in one YAML file, so that setup is simple and reviewable.

#### Acceptance Criteria

1. THE Config_File SHALL define, for each Button keyed by MAC address, the fields product name, ASIN, quantity, max_price, cooldown_days, and allow_substitutes.
2. THE Config_File SHALL define the global fields daily spend cap, dry_run (default true), and ntfy settings.
3. THE Config_File SHALL contain no secret value, and THE Agent_Service SHALL read the Nova Act API key, the ntfy_Access_Token, and AWS credentials from environment variables.
4. WHEN the Agent_Service loads the Config_File, THE Agent_Service SHALL validate every field and its type.
5. IF the Config_File fails validation, THEN THE Agent_Service SHALL exit with a message that names each invalid field.
6. IF two Button entries have the same MAC address after case normalization, THEN THE Agent_Service SHALL reject the Config_File.
7. THE Agent_Service SHALL normalize MAC addresses to lowercase colon-separated form.

### Requirement 18: Button Setup Command

**User Story:** As a home user, I want a setup command for a new button, so that I can join it to my Wi-Fi without the Amazon app.

#### Acceptance Criteria

1. WHEN the user runs `undash setup` with a Wi-Fi SSID and password while connected to the button ConfigureMe access point, THE CLI SHALL send an HTTP GET to http://192.168.0.1/ with the query parameters amzn_ssid and amzn_pw.
2. THE CLI SHALL URL-encode the SSID and password in the GET request.
3. WHEN the button responds, THE CLI SHALL print the serial number, MAC address, firmware version, and battery level.
4. IF the button does not respond within 10 seconds, THEN THE CLI SHALL exit with a non-zero status and a message that the ConfigureMe access point is unreachable.
5. THE CLI SHALL write the Wi-Fi password to no file and no log.
6. THE CLI SHALL send the Agent_User_Agent in the GET request.

### Requirement 19: Button Discovery Command

**User Story:** As a home user, I want to discover the MAC of a new button, so that I can add it to the config.

#### Acceptance Criteria

1. WHEN the user runs `undash discover`, THE CLI SHALL list the MAC addresses of recorded presses that are not in the Config_File.
2. THE CLI SHALL show for each listed MAC address the press count and the timestamp of the most recent press.
3. WHEN no unconfigured press has been recorded, THE CLI SHALL print a message that no unconfigured buttons were seen.
4. WHERE a pcap file path is supplied, THE CLI SHALL run discovery against the pcap file.

### Requirement 20: Test Coverage

**User Story:** As a maintainer, I want pytest coverage of the rules and state machine, so that money-handling logic is verified.

#### Acceptance Criteria

1. THE GhostShopper test suite SHALL cover each outcome of the Order_Rules: in-flight ignore, Cooldown ignore, out of stock, over max_price, substitute proposal, Daily_Spend_Cap exceeded, and approval.
2. THE GhostShopper test suite SHALL cover every allowed and every disallowed transition of the State_Machine.
3. THE GhostShopper test suite SHALL cover the Approval_Token cases: valid, unknown, used, and expired.
4. THE GhostShopper test suite SHALL cover the 10-minute approval timeout with a controllable clock.
5. THE GhostShopper test suite SHALL cover the Listener debounce using a pcap fixture.
6. THE GhostShopper test suite SHALL test the Buyer interaction through Python-level fakes of the Workflow_Client.
7. THE GhostShopper test suite SHALL run without network access, AWS credentials, or a Nova Act API key.
8. THE GhostShopper test suite SHALL achieve at least 95 percent line coverage of the Order_Rules and State_Machine modules.

### Requirement 21: Pi Image Build

**User Story:** As a maintainer, I want a CI-built Pi image, so that users can flash a ready system.

#### Acceptance Criteria

1. THE Image_Workflow SHALL build a minimal CustomPiOS image that contains the Listener and the Agent_Service.
2. THE Image_Workflow SHALL trigger on workflow_dispatch and on release tags matching v*.
3. THE Image_Workflow SHALL run on no ordinary push event.
4. WHEN the Image_Workflow completes, THE Image_Workflow SHALL publish the image as a workflow artifact.
5. WHEN the Image_Workflow runs on a v* tag, THE Image_Workflow SHALL attach the image to the matching GitHub release.
6. THE Image_Workflow SHALL embed no secret value in the image.

### Requirement 22: AWS Provisioning

**User Story:** As an AWS account owner, I want one command set to provision the cloud pieces with least privilege, so that the Pi can invoke only the buyer.

#### Acceptance Criteria

1. THE IaC_Stack SHALL define its resources in a single IaC tool chosen in the design (CDK or CloudFormation).
2. THE IaC_Stack SHALL create an IAM identity whose policy allows invoking only the specific AgentCore_Runtime endpoint of the Buyer.
3. THE IaC_Stack SHALL create the AgentCore_Browser Browser_Profile resource and the other resources the Buyer needs.
4. THE IaC_Stack SHALL grant the Invoke_Credential no permission to manage Browser_Profile resources, start browser sessions, or invoke other runtimes.
5. THE IaC_Stack SHALL grant the Buyer execution role only the permissions that the Buyer needs to start sessions with the Browser_Profile and to save the Browser_Profile.
6. THE README SHALL document the deploy steps for the IaC_Stack and how to create the Invoke_Credential access keys.
7. THE design document SHALL record each step that the IaC_Stack cannot perform, including the Amazon login through Live View and the Browser_Profile save.

### Requirement 23: README

**User Story:** As a new user, I want a README that walks me through hardware, network, and compliance, so that I can set the system up safely.

#### Acceptance Criteria

1. THE README SHALL describe the hardware setup: Raspberry Pi model, network placement, and button setup with `undash setup`.
2. THE README SHALL explain how to block the buttons from the internet at the Router.
3. THE README SHALL state that some buttons may hardcode DNS server 1.1.1.1, so that a Pi-hole alone may not block them.
4. THE README SHALL list the environment variables for the Nova Act API key, the ntfy_Access_Token, and AWS credentials.
5. THE README SHALL describe the Dry_Run default and the steps to set dry_run to false.
6. THE README SHALL describe how GhostShopper follows the Agent_Terms.
7. THE README SHALL state the known risk that concurrent approvals could exceed the Daily_Spend_Cap.

## Verified Platform Capabilities, Gaps, and Assumptions

Sources checked while writing this document: [Nova Act with AgentCore](https://docs.aws.amazon.com/nova-act/latest/userguide/bedrock-agentcore.html), [AgentCore browser profiles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-profiles.html), [AgentCore Live View](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-dcv-integration.html), [AgentCore Browser with Nova Act](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart-nova-act.html), [Nova Act README](https://github.com/aws/nova-act/blob/main/README.md), and a [secondary summary of the Amazon Agent Terms](https://www.sneeze.it/blog/checkouts-are-for-humans). Content was rephrased for compliance with licensing restrictions.

### Confirmed

- A Nova Act workflow deploys to AgentCore_Runtime, which provisions an endpoint for invocation.
- AgentCore_Browser profiles persist cookies and local storage. The flow is: create the profile, start a session, log in, call the save operation, then start new sessions with `profileConfiguration`.
- A profile save overwrites the previous profile data. Active sessions do not see later profile updates. Cookies expire on the site's own schedule, so the Amazon login will eventually need renewal.
- Live View is powered by AWS DCV, and the AgentCore console lets the user take over and release control of a running session.
- Nova Act connects to AgentCore_Browser through `cdp_endpoint_url` and `cdp_headers` obtained from the browser client.
- The Nova Act SDK has a `user_agent` option for browsers that Nova Act launches itself.
- Per the secondary summary, the Agent_Terms require every request to identify itself as `Agent/[agent name]`, forbid concealing agent status (for example by imitating human typing speed or circumventing CAPTCHAs), and require truthful answers about being non-human. Requirements 14.6 and 15 encode these rules.

### Gaps

- **User agent over CDP (unverified):** The Nova Act README states that proxy settings apply only when Nova Act launches the browser. The same limit probably applies to `user_agent`. No source confirms that AgentCore_Browser sessions accept a user agent setting. Requirement 15.2 therefore needs a mechanism chosen in the design (for example, a CDP user-agent override after connecting, or a custom browser setting if one exists). Requirements 15.3 and 15.4 act as a fail-closed check.
- **Profile start through the Nova Act helper (unverified):** The documented `browser_session` helper does not visibly accept a profile identifier. The documented profile flow calls `start_browser_session` with `profileConfiguration`. The design must confirm whether the helper supports profiles or whether the Buyer must call `start_browser_session` directly and then build CDP headers.
- **Live View access for the user:** The documented Live View URL is SigV4-presigned and needs credentials with browser permissions. The Invoke_Credential has none, by design. The user opens Live View from the AWS console under their own identity, and the verification_required notification can only point to the console, not to a presigned link.
- **Nova Act authentication:** The AgentCore quickstart says the Nova Act API key works only with US-based amazon.com accounts. GhostShopper is therefore limited to US amazon.com. Nova Act also offers AWS IAM-based authentication, and the design must choose between the API key (required by this spec) and IAM.
- **Runtime invocation duration (unverified):** The 10-minute re-verification wait, plus page work, may exceed the synchronous invocation limit of AgentCore_Runtime. The design must check the limit and, if needed, use an asynchronous invocation with status polling.
- **IAM action and resource names (unverified):** The exact IAM action and endpoint ARN format for invoking one AgentCore_Runtime endpoint need confirmation from current IAM reference documentation during design.
- **Dash press signature:** Dash buttons are identified by ARP probe or DHCP request. No authoritative list of Amazon OUIs is bundled, so the Listener forwards candidates and the Agent_Service decides by Config_File membership.
- **Amazon Agent Terms text:** The primary Amazon page could not be fetched. The rules above come from a secondary summary and must be re-read from the Amazon Conditions of Use before release.

### Assumptions

- Orders that fail Order_Rules checks (out of stock, over max_price, spend cap) end in state failed with a reason code, because the required state list has no dedicated rejected state.
- A Dry_Run Order ends in state placed with a dry_run flag and without an order number. Dry_Run Orders do not count toward Cooldown or the Daily_Spend_Cap.
- Cooldown starts at the timestamp of the most recent real Order in state placed.
- The Daily_Spend_Cap day boundary uses the time zone of the Agent_Service host.
- The Listener forwards presses from any MAC address that matches the Dash press signature, so that `undash discover` can find new buttons.
- The max_price check applies to the configured product and to any Substitute.
- The approval message always goes to the user, including for the configured product, because the order rules require approval before every purchase.

### Risks

- **Concurrent approvals can exceed the Daily_Spend_Cap.** The cap counts only Orders in state placed. Two Orders in state approved or ordering at the same time are each checked against placed spend alone, so their combined price can exceed the cap. This is an accepted decision. Requirement 9.10 serializes the check-and-transition step, but it does not count in-flight Orders.
- A purchase interrupted by an Agent_Service restart has an unknown outcome. Requirement 10.5 marks the Order failed and asks the user to check the Amazon account.
- The Browser_Profile holds Amazon session cookies. A user with broad AgentCore permissions in the same AWS account can use them. The IaC_Stack limits the Invoke_Credential, but not other identities in the account.
