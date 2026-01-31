# OAuth Setup for Public Distribution

This guide explains how to configure IncidentFox Slack Bot for public distribution with OAuth.

## Prerequisites

1. **Domain Name**: You need a custom domain (e.g., `incidentfox.com`)
2. **AWS ACM Certificate**: SSL/TLS certificate for HTTPS
3. **Slack App**: Configured for public distribution

## Step 1: Get OAuth Credentials

1. Go to https://api.slack.com/apps
2. Select your app
3. **Basic Information** → **App Credentials**:
   - Copy **Client ID** → Set as `SLACK_CLIENT_ID`
   - Copy **Client Secret** → Set as `SLACK_CLIENT_SECRET`
   - Copy **Signing Secret** → Set as `SLACK_SIGNING_SECRET`

## Step 2: Request ACM Certificate

```bash
# Request certificate for your domain
aws acm request-certificate \
  --domain-name slack-bot.incidentfox.com \
  --validation-method DNS \
  --region us-west-2

# Get certificate ARN
aws acm list-certificates --region us-west-2
```

Follow the email validation or DNS validation steps to verify domain ownership.

## Step 3: Configure HTTPS LoadBalancer

Update `/Users/jimmywei/conductor/workspaces/incidentfox/muscat/slack-bot/k8s/service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: slack-bot-svc
  namespace: incidentfox-prod
  labels:
    app: slack-bot
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internet-facing"
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    # Add ACM certificate ARN for HTTPS
    service.beta.kubernetes.io/aws-load-balancer-ssl-cert: "arn:aws:acm:us-west-2:ACCOUNT:certificate/CERT_ID"
    service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"
    service.beta.kubernetes.io/aws-load-balancer-backend-protocol: "http"
spec:
  type: LoadBalancer
  ports:
    - port: 443
      targetPort: 3000
      protocol: TCP
      name: https
  selector:
    app: slack-bot
```

Or use Application Load Balancer (ALB) with Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: slack-bot-ingress
  namespace: incidentfox-prod
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-west-2:ACCOUNT:certificate/CERT_ID
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
spec:
  ingressClassName: alb
  rules:
    - host: slack-bot.incidentfox.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: slack-bot-svc
                port:
                  number: 80
```

## Step 4: Update Secrets

Add OAuth credentials to Kubernetes secrets:

```bash
kubectl create secret generic slack-bot-secrets \
  --namespace=incidentfox-prod \
  --from-literal=slack-client-id="${SLACK_CLIENT_ID}" \
  --from-literal=slack-client-secret="${SLACK_CLIENT_SECRET}" \
  --from-literal=slack-signing-secret="${SLACK_SIGNING_SECRET}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Update deployment to use OAuth secrets:

```yaml
env:
  - name: SLACK_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: slack-bot-secrets
        key: slack-client-id
  - name: SLACK_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: slack-bot-secrets
        key: slack-client-secret
  - name: SLACK_SIGNING_SECRET
    valueFrom:
      secretKeyRef:
        name: slack-bot-secrets
        key: slack-signing-secret
```

## Step 5: Configure Slack App for OAuth

1. Go to https://api.slack.com/apps
2. Select your app
3. **OAuth & Permissions**:
   - **Redirect URLs**: Add:
     - `https://slack-bot.incidentfox.com/slack/oauth_redirect`
   - Click **Save URLs**

4. **Manage Distribution** → **Public Distribution**:
   - **Add OAuth Redirect URLs**: ✅ Complete
   - **Remove Hard Coded Information**: Remove `SLACK_BOT_TOKEN` from production secrets
   - **Use HTTPS For Your Features**: ✅ Complete (after Step 3)
   - Click **Activate Public Distribution**

## Step 6: Deploy

```bash
cd slack-bot
make deploy-prod
```

Get your public URL:
```bash
make prod-url
```

## Step 7: Test OAuth Flow

Share your app installation link:
```
https://slack.com/oauth/v2/authorize?client_id=YOUR_CLIENT_ID&scope=app_mentions:read,chat:write,channels:history,files:write&redirect_uri=https://slack-bot.incidentfox.com/slack/oauth_redirect
```

Or use the Install button URL:
```
https://slack-bot.incidentfox.com/slack/install
```

## Architecture

```
User clicks "Add to Slack"
    │
    ▼
Slack Authorization Page
    │
    │ User approves
    ▼
Redirect to /slack/oauth_redirect
    │
    │ Exchange code for token
    ▼
Store installation in /app/data/installations
    │
    ▼
Bot ready for that workspace!
```

## Troubleshooting

### Installation tokens not persisting

Add a PersistentVolume to store installations:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: slack-bot-data
  namespace: incidentfox-prod
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

Mount in deployment:
```yaml
volumeMounts:
  - name: slack-data
    mountPath: /app/data
volumes:
  - name: slack-data
    persistentVolumeClaim:
      claimName: slack-bot-data
```

### DNS not resolving

Update Route 53 to point to your LoadBalancer:
```bash
aws route53 change-resource-record-sets --hosted-zone-id Z1234567890ABC \
  --change-batch file://dns-record.json
```

Where `dns-record.json`:
```json
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "slack-bot.incidentfox.com",
      "Type": "CNAME",
      "TTL": 300,
      "ResourceRecords": [{"Value": "k8s-incident-slackbot-xxx.elb.us-west-2.amazonaws.com"}]
    }
  }]
}
```

## Security

- OAuth tokens are stored in `/app/data/installations` (file-based)
- For production at scale, consider using a database installation store
- All communication with Slack uses HTTPS
- Signatures are verified on all incoming requests
