#!/bin/bash
# Create RDS instance for config-service in EKS VPC
# Run this ONCE for initial setup. Subsequent deployments use deploy-eks.sh
set -e

REGION="us-west-2"
EKS_VPC="vpc-0d0acec56464027c2"
RDS_INSTANCE_ID="incidentfox-prod-config"
DB_NAME="configservice"
DB_USERNAME="configadmin"

echo "🗄️  Setting up RDS for config-service"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if RDS already exists
EXISTING=$(aws rds describe-db-instances --db-instance-identifier $RDS_INSTANCE_ID --region $REGION 2>/dev/null || echo "")
if [ -n "$EXISTING" ]; then
  echo "✅ RDS instance already exists: $RDS_INSTANCE_ID"
  RDS_ENDPOINT=$(echo "$EXISTING" | jq -r '.DBInstances[0].Endpoint.Address')
  echo "   Endpoint: $RDS_ENDPOINT"
  exit 0
fi

# Step 1: Get EKS private subnets
echo "1️⃣  Getting EKS private subnets..."
PRIVATE_SUBNETS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$EKS_VPC" "Name=tag:Name,Values=*Private*" \
  --region $REGION \
  --query 'Subnets[*].SubnetId' \
  --output text | tr '\t' ' ')

if [ -z "$PRIVATE_SUBNETS" ]; then
  # Fallback: use known subnet IDs
  PRIVATE_SUBNETS="subnet-0369308e8e9955907 subnet-00873819747ff89db subnet-05072ea753216a4a2"
fi
echo "   Subnets: $PRIVATE_SUBNETS"

# Step 2: Create DB subnet group
echo ""
echo "2️⃣  Creating DB subnet group..."
aws rds create-db-subnet-group \
  --db-subnet-group-name incidentfox-prod-rds \
  --db-subnet-group-description "RDS subnet group in EKS VPC" \
  --subnet-ids $PRIVATE_SUBNETS \
  --region $REGION 2>/dev/null || echo "   (already exists)"
echo "   ✅ Subnet group ready"

# Step 3: Create security group for RDS
echo ""
echo "3️⃣  Creating RDS security group..."

# Get EKS node security groups
EKS_NODE_SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$EKS_VPC" "Name=group-name,Values=*ClusterSharedNodeSecurityGroup*" \
  --region $REGION \
  --query 'SecurityGroups[0].GroupId' \
  --output text)

EKS_CLUSTER_SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$EKS_VPC" "Name=group-name,Values=eks-cluster-sg-*" \
  --region $REGION \
  --query 'SecurityGroups[0].GroupId' \
  --output text)

# Check if RDS security group exists
RDS_SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$EKS_VPC" "Name=group-name,Values=incidentfox-prod-rds" \
  --region $REGION \
  --query 'SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || echo "None")

if [ "$RDS_SG" == "None" ] || [ -z "$RDS_SG" ]; then
  RDS_SG=$(aws ec2 create-security-group \
    --group-name incidentfox-prod-rds \
    --description "RDS security group for config-service" \
    --vpc-id $EKS_VPC \
    --region $REGION \
    --query 'GroupId' \
    --output text)
  echo "   Created security group: $RDS_SG"

  # Add inbound rules
  aws ec2 authorize-security-group-ingress \
    --group-id $RDS_SG \
    --protocol tcp \
    --port 5432 \
    --source-group $EKS_NODE_SG \
    --region $REGION 2>/dev/null || true

  aws ec2 authorize-security-group-ingress \
    --group-id $RDS_SG \
    --protocol tcp \
    --port 5432 \
    --source-group $EKS_CLUSTER_SG \
    --region $REGION 2>/dev/null || true
else
  echo "   Security group exists: $RDS_SG"
fi
echo "   ✅ Security group ready"

# Step 4: Generate password and create secrets
echo ""
echo "4️⃣  Generating credentials..."
DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

aws secretsmanager create-secret \
  --name "incidentfox/prod/rds" \
  --description "RDS credentials for config-service" \
  --secret-string "{\"host\":\"TBD\",\"port\":\"5432\",\"dbname\":\"$DB_NAME\",\"username\":\"$DB_USERNAME\",\"password\":\"$DB_PASSWORD\"}" \
  --region $REGION 2>/dev/null || \
aws secretsmanager update-secret \
  --secret-id "incidentfox/prod/rds" \
  --secret-string "{\"host\":\"TBD\",\"port\":\"5432\",\"dbname\":\"$DB_NAME\",\"username\":\"$DB_USERNAME\",\"password\":\"$DB_PASSWORD\"}" \
  --region $REGION

echo "   ✅ Credentials stored in Secrets Manager"

# Step 5: Create RDS instance
echo ""
echo "5️⃣  Creating RDS instance (this takes 5-10 minutes)..."
aws rds create-db-instance \
  --db-instance-identifier $RDS_INSTANCE_ID \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version "16.6" \
  --master-username $DB_USERNAME \
  --master-user-password "$DB_PASSWORD" \
  --allocated-storage 20 \
  --db-subnet-group-name incidentfox-prod-rds \
  --vpc-security-group-ids $RDS_SG \
  --db-name $DB_NAME \
  --storage-encrypted \
  --no-publicly-accessible \
  --backup-retention-period 7 \
  --region $REGION \
  --output json > /dev/null

echo "   Waiting for RDS to be available..."
aws rds wait db-instance-available --db-instance-identifier $RDS_INSTANCE_ID --region $REGION

# Step 6: Update secrets with endpoint
RDS_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier $RDS_INSTANCE_ID \
  --region $REGION \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

CURRENT_SECRET=$(aws secretsmanager get-secret-value --secret-id "incidentfox/prod/rds" --region $REGION --query 'SecretString' --output text)
UPDATED_SECRET=$(echo "$CURRENT_SECRET" | jq --arg host "$RDS_ENDPOINT" '.host = $host')
aws secretsmanager update-secret --secret-id "incidentfox/prod/rds" --secret-string "$UPDATED_SECRET" --region $REGION

echo ""
echo "✅ RDS SETUP COMPLETE!"
echo ""
echo "RDS Instance: $RDS_INSTANCE_ID"
echo "Endpoint: $RDS_ENDPOINT"
echo "Database: $DB_NAME"
echo "Username: $DB_USERNAME"
echo ""
echo "Next: Run deploy-eks.sh to deploy config-service"
