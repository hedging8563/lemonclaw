# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in LemonClaw, please report it by:

1. **DO NOT** open a public GitHub issue
2. Create a private security advisory on GitHub or contact the maintainers (security@lemondata.cc)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We aim to respond to security reports within 48 hours.

## Security Best Practices

### 1. API Key Management

**CRITICAL**: Never commit API keys to version control.

```bash
# ✅ Good: Store in config file with restricted permissions
chmod 600 ~/.lemonclaw/config.json

# ❌ Bad: Hardcoding keys in code or committing them
```

**Recommendations:**
- Store API keys in `~/.lemonclaw/config.json` with file permissions set to `0600`
- Consider using environment variables for sensitive keys
- Use OS keyring/credential manager for production deployments
- Rotate API keys regularly
- Use separate API keys for development and production

### 2. Channel Access Control

**IMPORTANT**: Always configure `allowFrom` lists for production use.

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789", "987654321"]
    },
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

**Security Notes:**
- Empty `allowFrom` list will **ALLOW ALL** users (open by default for personal use)
- Get your Telegram user ID from `@userinfobot`
- Use full phone numbers with country code for WhatsApp
- Review access logs regularly for unauthorized access attempts

### 3. Gateway Security

The LemonClaw gateway exposes an HTTP endpoint for health checks and management.

**Default (fail-closed):**
- `bind: "localhost"` — only accessible from the local machine
- `auth_token: null` — rejects non-localhost requests when no token is set

**K8s deployment:**
```bash
# Explicitly open for K8s probes
GATEWAY_BIND=0.0.0.0
GATEWAY_TOKEN=your-secret-token
```

**Recommendations:**
- Always set `GATEWAY_TOKEN` when binding to `0.0.0.0`
- Use K8s NetworkPolicy to restrict access to the gateway port (18789)
- Never expose the gateway port via NodePort without authentication

### 4. Shell Command Execution

The `exec` tool can execute shell commands. In the current Full-Power deployment model, the real security boundary is the container / host, not a workspace sandbox.

**Self-hosted dedicated machine:**
- ✅ Review all tool usage in agent logs
- ✅ Understand what commands the agent is running
- ✅ Prefer a dedicated machine or dedicated user account for LemonClaw
- ❌ Don't run on systems with unrelated sensitive data unless you accept full local access risk

**K8s full-power deployment:**
- ✅ Treat the Pod / container boundary as the primary control
- ✅ Ensure no Docker / container runtime sockets are mounted
- ✅ Ensure no broad hostPath mounts are exposed to the Pod
- ✅ Review whether overlay mounts require elevated container privileges in your cluster
- ❌ Don't assume application-level deny patterns are your main security boundary

**Blocked patterns:**
- `rm -rf /` — Root filesystem deletion
- Fork bombs
- Filesystem formatting (`mkfs.*`)
- Raw disk writes
- Other destructive operations

### 5. File System Access

LemonClaw now assumes a Full-Power local tools model in dedicated deployments.

- ✅ Use deployment isolation (container / Pod / host separation) as the main boundary
- ✅ Keep persistent data under controlled paths such as `~/.lemonclaw`
- ✅ Regularly audit file operations in logs
- ❌ Don't colocate LemonClaw with unrelated high-value secrets unless you accept full local access risk

### 6. Network Security

**API Calls:**
- All external API calls use HTTPS by default
- Timeouts are configured to prevent hanging requests
- Consider using a firewall to restrict outbound connections if needed

**WhatsApp Bridge:**
- The bridge binds to `127.0.0.1:3001` (localhost only)
- Set `bridgeToken` in config to enable shared-secret authentication
- Keep authentication data in `~/.lemonclaw/whatsapp-auth` secure (mode 0700)

### 7. Dependency Security

**Critical**: Keep dependencies updated!

```bash
# Check for vulnerable dependencies
pip install pip-audit
pip-audit

# Update to latest secure versions
pip install --upgrade lemonclaw
```

For Node.js dependencies (WhatsApp bridge):
```bash
cd bridge
npm audit
npm audit fix
```

### 8. Production Deployment

For production use:

1. **Isolate the Environment**
   ```bash
   # Run in a container or VM
   docker run --rm -it python:3.12
   pip install lemonclaw
   ```

2. **Use a Dedicated User**
   ```bash
   sudo useradd -m -s /bin/bash lemonclaw
   sudo -u lemonclaw lemonclaw gateway
   ```

3. **Set Proper Permissions**
   ```bash
   chmod 700 ~/.lemonclaw
   chmod 600 ~/.lemonclaw/config.json
   chmod 700 ~/.lemonclaw/whatsapp-auth
   ```

4. **Enable Logging**
   ```bash
   # K8s: logs go to stdout/stderr (kubectl logs)
   # Self-hosted: check log file
   tail -f ~/.lemonclaw/lemonclaw.log
   ```

5. **Use Rate Limiting**
   - Configure rate limits on your LemonData API key
   - Monitor usage for anomalies
   - Set spending limits in the LemonData dashboard

6. **Regular Updates**
   ```bash
   pip install --upgrade lemonclaw
   ```

### 9. Data Privacy

- **Logs may contain sensitive information** — secure log files appropriately
- **LLM providers see your prompts** — review their privacy policies
- **Chat history is stored locally** — protect the `~/.lemonclaw` directory
- **API keys are in plain text** — use OS keyring for production

### 10. Incident Response

If you suspect a security breach:

1. **Immediately revoke compromised API keys** (LemonData dashboard → API Keys)
2. **Review logs for unauthorized access**
   ```bash
   grep "Access denied" ~/.lemonclaw/lemonclaw.log
   ```
3. **Check for unexpected file modifications**
4. **Rotate all credentials** (API keys, Telegram bot token, gateway token)
5. **Update to latest version**
6. **Report the incident** to maintainers

## Security Features

### Built-in Security Controls

✅ **Input Validation**
- Path traversal protection on file operations
- Dangerous command pattern detection
- Input length limits on HTTP requests

✅ **Authentication**
- Allow-list based access control per channel
- Gateway auth_token for management endpoints
- Failed authentication attempt logging

✅ **Resource Protection**
- Command execution timeouts (60s default)
- Output truncation (10KB limit)
- HTTP request timeouts (10-30s)
- Watchdog: memory pressure detection + stuck session recovery

✅ **Secure Communication**
- HTTPS for all external API calls (LemonData API)
- TLS for Telegram API
- WhatsApp bridge: localhost-only binding + optional token auth

## Known Limitations

⚠️ **Current Security Limitations:**

1. **No Rate Limiting** — Users can send unlimited messages (add your own if needed)
2. **Plain Text Config** — API keys stored in plain text (use keyring for production)
3. **No Session Management** — No automatic session expiry
4. **Limited Command Filtering** — Only blocks obvious dangerous patterns
5. **No Audit Trail** — Limited security event logging (enhance as needed)

## Security Checklist

Before deploying LemonClaw:

- [ ] API keys stored securely (not in code)
- [ ] Config file permissions set to 0600
- [ ] `allowFrom` lists configured for all channels
- [ ] Gateway `auth_token` set (if binding to 0.0.0.0)
- [ ] Running as non-root user
- [ ] File system permissions properly restricted
- [ ] Dependencies updated to latest secure versions
- [ ] Logs monitored for security events
- [ ] Rate limits configured on LemonData dashboard
- [ ] Backup and disaster recovery plan in place
- [ ] Security review of custom skills/tools

## Updates

**Last Updated**: 2026-02-28

For the latest security updates and announcements, check:
- GitHub Releases: https://github.com/hedging8563/lemonclaw/releases

## License

See LICENSE file for details.
