# Public Distribution Checklist

## ✅ Completed Steps

1. **OAuth Implementation**
   - Added OAuth support with FileInstallationStore
   - App now supports both single-workspace and multi-workspace modes
   - OAuth routes implemented: `/slack/install`, `/slack/oauth_redirect`
   - Falls back to single-workspace mode if OAuth credentials not provided

2. **HTTP Mode**
   - Bot running in HTTP mode (production-ready)
   - Webhook URL verified by Slack ✓
   - Event Subscriptions configured and working

3. **Security**
   - Signature verification enabled
   - Internal sre-agent service (ClusterIP)
   - Only slack-bot is public-facing

## ⚠️ Remaining Steps for Public Distribution

### 1. Enable HTTPS (Required)

**Option A: NLB with ACM Certificate**
```yaml
annotations:
  service.beta.kubernetes.io/aws-load-balancer-ssl-cert: "arn:aws:acm:us-west-2:XXX:certificate/YYY"
  service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
  service.beta.kubernetes.io/aws-load-balancer-backend-protocol: "http"
```

**Option B: ALB with Ingress (Recommended)**
- Better for HTTP/HTTPS traffic
- Automatic certificate management
- Path-based routing
- See `OAUTH_SETUP.md` for full configuration

**Steps:**
1. Get a domain name (e.g., `slack-bot.incidentfox.com`)
2. Request ACM certificate:
   ```bash
   aws acm request-certificate \
     --domain-name slack-bot.incidentfox.com \
     --validation-method DNS \
     --region us-west-2
   ```
3. Validate domain ownership (DNS or email)
4. Update service.yaml with certificate ARN
5. Configure DNS to point to LoadBalancer

### 2. Configure OAuth Redirect URLs

**Current URL (HTTP - temporary):**
```
http://k8s-incident-slackbot-2bcb6a4d35-d49c57ac6d2c54f0.elb.us-west-2.amazonaws.com
```

**Required URLs (HTTPS):**
```
https://slack-bot.incidentfox.com/slack/oauth_redirect
https://slack-bot.incidentfox.com/slack/install
```

**Slack Configuration:**
1. Go to https://api.slack.com/apps → Your App
2. **OAuth & Permissions** → **Redirect URLs**
3. Add: `https://slack-bot.incidentfox.com/slack/oauth_redirect`
4. Save URLs

### 3. Get OAuth Credentials

1. Go to https://api.slack.com/apps → Your App
2. **Basic Information** → **App Credentials**
3. Copy:
   - Client ID → `SLACK_CLIENT_ID`
   - Client Secret → `SLACK_CLIENT_SECRET`
   - Signing Secret → `SLACK_SIGNING_SECRET` (already have this)

4. Add to `.env` file:
   ```bash
   SLACK_CLIENT_ID=your-client-id
   SLACK_CLIENT_SECRET=your-client-secret
   ```

5. Redeploy with OAuth credentials:
   ```bash
   cd slack-bot
   make deploy-prod
   ```

### 4. Remove Hardcoded Tokens

Once OAuth is configured:
1. Remove `SLACK_BOT_TOKEN` from production secrets
2. Keep `SLACK_BOT_TOKEN` only for local dev/testing
3. Production will use OAuth installation tokens

### 5. Activate Public Distribution

1. Go to **Manage Distribution** → **Public Distribution**
2. Complete checklist:
   - [x] Enable Features & Functionality
   - [ ] Add OAuth Redirect URLs (Step 2)
   - [ ] Remove Hard Coded Information (Step 4)
   - [ ] Use HTTPS For Your Features (Step 1)
3. Click **Activate Public Distribution**

## Current Architecture

```
Internet
    │
    │ HTTP (temporary)
    ▼
NLB (internet-facing)
    │
    │ Port 80 → 3000
    ▼
slack-bot pods (2 replicas)
    │
    │ Internal K8s service
    ▼
sre-agent (ClusterIP)
```

## Target Architecture (with HTTPS)

```
Internet
    │
    │ HTTPS (port 443)
    ▼
ALB/NLB + ACM Certificate
    │
    │ TLS termination
    │ HTTP → 3000
    ▼
slack-bot pods (2 replicas)
    │
    │ OAuth installations stored in /app/data
    │
    │ Internal K8s service
    ▼
sre-agent (ClusterIP)
```

## Testing OAuth Flow

Once HTTPS is configured:

1. **Installation Link:**
   ```
   https://slack-bot.incidentfox.com/slack/install
   ```

2. **Manual OAuth URL:**
   ```
   https://slack.com/oauth/v2/authorize?client_id=YOUR_CLIENT_ID&scope=app_mentions:read,chat:write,channels:history,files:write&redirect_uri=https://slack-bot.incidentfox.com/slack/oauth_redirect
   ```

3. User clicks → Slack authorization → Redirects back → Token stored → Bot ready!

## Quick Start Commands

```bash
# 1. Get domain and ACM certificate ready first

# 2. Add OAuth credentials to .env
cat >> /path/to/muscat/.env << EOF
SLACK_CLIENT_ID=your-client-id
SLACK_CLIENT_SECRET=your-client-secret
EOF

# 3. Deploy with OAuth support
cd slack-bot
make deploy-prod

# 4. Verify deployment
make prod-url

# 5. Test OAuth flow by visiting:
# https://slack-bot.incidentfox.com/slack/install
```

## Monitoring

```bash
# Check pod logs for OAuth
kubectl logs -n incidentfox-prod -l app=slack-bot --tail=50 -f

# Verify installations are being stored
kubectl exec -n incidentfox-prod deployment/slack-bot -- ls -la /app/data/installations

# Check OAuth flow
kubectl logs -n incidentfox-prod -l app=slack-bot | grep -i "oauth"
```

## Next Steps

1. **Immediate:** Get a domain name for your slack-bot
2. **Immediate:** Request ACM certificate for that domain
3. **After certificate issued:** Update k8s/service.yaml with HTTPS
4. **After HTTPS working:** Configure OAuth redirect URLs in Slack
5. **After OAuth configured:** Remove hardcoded SLACK_BOT_TOKEN from production
6. **Finally:** Activate public distribution

## References

- [Slack OAuth Documentation](https://api.slack.com/authentication/oauth-v2)
- [Installing with OAuth](https://api.slack.com/authentication/installing-with-oauth)
- [Public Distribution](https://api.slack.com/start/distributing/public)
- Full setup guide: `OAUTH_SETUP.md`
