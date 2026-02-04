# IncidentFox Customer Documentation

**Welcome!** This directory contains all documentation for installing and using IncidentFox in your environment.

---

## 🚀 Getting Started

**New customer?** Start here:

1. **[Infrastructure Setup](./infrastructure-setup.md)** - Choose your deployment path
   - Terraform (automated)
   - AWS Console (click-ops)
   - Bring your own infrastructure
   - Managed service

2. **[Installation Guide](./installation-guide.md)** - Install IncidentFox with Helm
   - Prerequisites
   - Secret management
   - Helm deployment
   - Verification

3. **[Onboarding Overview](./onboarding.md)** - What's included in your package
   - Docker images
   - Helm charts
   - Documentation
   - Support resources

4. **[Kubernetes Integration](./kubernetes-integration.md)** - Connect your K8s clusters (SaaS)
   - Agent deployment via Helm
   - RBAC configuration
   - Multiple cluster support

---

## 📚 Quick Links

### Installation Paths

| Path | Best For | Time | Guide |
|------|----------|------|-------|
| **Terraform** | DevOps teams | 30 min | [Terraform Guide](./terraform-guide.md) |
| **AWS Console** | Small teams | 2-3 hours | [Console Guide](./console-guide.md) |
| **BYO Infra** | Existing setup | 0 min | [Installation Guide](./installation-guide.md#phase-4-helm-installation) |

### Terraform Modules

Pre-built infrastructure templates:
- **Complete Stack**: [customer-terraform/aws/complete/](../../customer-terraform/aws/complete/)
- **Minimal Stack**: [customer-terraform/aws/minimal/](../../customer-terraform/aws/minimal/)

### API Reference

After installation, use these APIs for automation:
- **[API Reference Guide](./api-reference.md)** - Complete API documentation
  - Organization & team management
  - Token generation & revocation
  - Agent execution
  - Configuration management

---

## 🎯 Common Use Cases

### "I'm starting from scratch on AWS"
1. Read: [Infrastructure Setup](./infrastructure-setup.md)
2. Choose: PATH 1 (Terraform)
3. Follow: [Terraform Guide](./terraform-guide.md)
4. Continue: [Installation Guide](./installation-guide.md#phase-4-helm-installation)

### "I already have Kubernetes and PostgreSQL"
1. Skip infrastructure setup
2. Go directly to: [Installation Guide](./installation-guide.md)

### "I'm not technical, need step-by-step"
1. Read: [Infrastructure Setup](./infrastructure-setup.md)
2. Choose: PATH 3 (Console)
3. Follow: [Console Guide](./console-guide.md)
4. Continue: [Installation Guide](./installation-guide.md#phase-4-helm-installation)

---

## 📖 Document Structure

```
docs/customer/
├── README.md (you are here)          # Start here
├── infrastructure-setup.md           # Choose deployment path
├── terraform-guide.md                # PATH 1: Terraform
├── console-guide.md                  # PATH 3: AWS Console
├── installation-guide.md             # Main installation steps
├── kubernetes-integration.md         # Connect K8s clusters (SaaS)
├── api-reference.md                  # API endpoints & examples
└── onboarding.md                     # Package contents
```

---

## 💬 Support

- **Email**: support@incidentfox.ai
- **Documentation**: This directory
- **License Key**: Contact sales@incidentfox.ai

---

## 📦 What You Need

Before starting, gather:
- ✅ IncidentFox license key (from sales)
- ✅ AWS account (if creating new infrastructure)
- ✅ OpenAI API key (or compatible LLM)
- ✅ Domain name for IncidentFox
- ✅ (Optional) Slack/GitHub/PagerDuty credentials

---

## ⏱️ Time Estimates

| Task | Time |
|------|------|
| Infrastructure setup (Terraform) | 30 min setup + 20 min apply |
| Infrastructure setup (Console) | 2-3 hours |
| Helm installation | 30 min |
| Initial configuration | 30 min |
| **Total (new deployment)** | **2-4 hours** |

---

## 🔐 Security Note

All customer documentation is public in this repository. Your credentials, license keys, and configuration values should NEVER be committed to version control.

- Store secrets in AWS Secrets Manager, HashiCorp Vault, or similar
- Use `terraform.tfvars` (add to .gitignore)
- Use Kubernetes secrets for sensitive data

---

## 🎓 Learning Resources

New to these technologies?

- **Kubernetes**: https://kubernetes.io/docs/tutorials/
- **Helm**: https://helm.sh/docs/intro/quickstart/
- **Terraform**: https://developer.hashicorp.com/terraform/tutorials
- **AWS EKS**: https://docs.aws.amazon.com/eks/latest/userguide/

---

**Ready to get started?** → [Infrastructure Setup](./infrastructure-setup.md)
