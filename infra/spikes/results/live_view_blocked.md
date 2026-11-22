# Live View blocked (found while preparing spikes 2 and 4)

- Date: 2026-11-22
- Result: **BLOCKED on AWS side**. Spikes 2 and 4 cannot run until Live View works.

## Observations

- Account had no browser profile (`list-browser-profiles` returned none).
- Session `01M82GA9VFWPN3SBFK5NSR71WW` (us-east-1, `aws.browser.v1`, started with the CLI) reports `READY`.
- Console Live View never renders a frame. The DCV client's `wss://.../live-view/auth` handshake returns **HTTP 404**, in both Firefox and Chrome, with VPN, Pi-hole and extensions off.
- `get-browser-session` shows `automationStream.streamStatus = ENABLED`, while `liveViewStream` has an endpoint but **no `streamStatus` field**.
- The AWS console cannot start sessions on the managed `aws.browser.v1` tool, so a console-started session could not be compared.
- `probe_live_view.py` (bare WebSocket, not a DCV client) got 400 on `/auth` and 404 on the main channel in both us-east-1 and us-west-2. Not conclusive, because the probe does not speak DCV.
- IAM: `iam simulate-principal-policy` shows `ConnectBrowserLiveViewStream` and `ConnectBrowserAutomationStream` both **allowed** for the operator identity.

## Findings that feed the design

- CDP automation works on the same session (`Page.navigate` via the automation stream succeeded).
- While the console holds "Take control", the automation WebSocket is refused with **HTTP 403**; it works again after "Return control to tool". This confirms the design rule that the Buyer's verification waiter must tolerate connection errors and re-attach (design.md, "Verification wait").

## Next step

AWS Support or re:Post case with the session ID, region, the 404 on `/live-view/auth`, and the missing `liveViewStream.streamStatus`.
