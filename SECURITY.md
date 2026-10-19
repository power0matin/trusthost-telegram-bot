# Security Policy

## Supported versions
Only the latest release receives security fixes.

## Reporting a vulnerability
Please do **not** open a public issue. Use GitHub's private reporting:
**Security tab → Report a vulnerability** on this repository.

Include steps to reproduce, the affected version, and the impact. You will get a response as soon as possible.

## Handling credentials
- Never paste `.env`, API secrets (`th_sec_...`) or bot tokens in issues, logs or screenshots.
- If a credential leaks, revoke it immediately (TrustHost client area for API keys, @BotFather `/revoke` for the bot token) and re-run `install.sh --reconfigure`.
- Restrict the TrustHost API key to your server's public IP.