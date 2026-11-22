# Product: GhostShopper

GhostShopper revives retired Amazon Dash buttons. A physical button press becomes a reorder of a configured Amazon product, with a human approving every purchase from a phone notification.

## Who it is for

A home user with old Dash buttons, a Raspberry Pi, an AWS account, and a US amazon.com account.

## Core flow

1. A Raspberry Pi sniffs ARP/DHCP traffic and detects a button press.
2. The agent service applies plain-Python order rules (in-flight, cooldown, spend cap).
3. A cloud buyer (Nova Act workflow on AWS AgentCore Runtime and AgentCore Browser) reads title, price, availability, and delivery estimate.
4. The user receives an ntfy notification: "<product> is $X, arriving <date>. Approve?"
5. On approval the buyer uses Buy Now and returns the order number. A timeout of 10 minutes counts as deny.

## Principles

- Rules are code, not model output. The model only reads pages and clicks. It never decides whether to buy.
- A human approves every purchase. Substitute products always need approval.
- GhostShopper never sees or stores an Amazon password or card number. The Amazon login lives in an AgentCore Browser profile that the user creates through Live View.
- Dry run is the default. A dry run stops before the final Place Order click.
- GhostShopper identifies itself to Amazon. Every request carries a user agent that includes `Agent/ghostshopper`. It does not solve CAPTCHAs or imitate human timing.
- The home network accepts no inbound connections. ntfy replies arrive over an outbound stream.

## Out of scope

- Mock stores, S3 static sites, and related-item browsing.
- Any x86 host or local Chrome/Playwright.
- Stores other than amazon.com (US).
