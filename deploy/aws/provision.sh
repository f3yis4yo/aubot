#!/bin/bash
# Create the AWS resources for AUBOT (idempotent where practical). Run once from your machine:
#   deploy/aws/provision.sh
# Region: Sydney (ap-southeast-2) so customer data stays in Australia.
set -euo pipefail
export AWS_REGION=${AWS_REGION:-ap-southeast-2} AWS_PAGER=""
NAME=aubot
HERE=$(cd "$(dirname "$0")" && pwd)
STATE="$HERE/.state"
KEY_FILE="$HOME/.ssh/aubot-aws.pem"
INSTANCE_TYPE=${INSTANCE_TYPE:-t3.micro}

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="${NAME}-backups-${ACCOUNT}-${AWS_REGION}"
MY_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')
echo "Account $ACCOUNT, region $AWS_REGION, your IP $MY_IP"

# --- SSH key pair (private key stays on this machine) ---
if ! aws ec2 describe-key-pairs --key-names "${NAME}-key" >/dev/null 2>&1; then
  mkdir -p "$HOME/.ssh"
  aws ec2 create-key-pair --key-name "${NAME}-key" --key-type ed25519 --query KeyMaterial --output text > "$KEY_FILE"
  chmod 400 "$KEY_FILE"
fi

# --- Security group: web open to all, SSH only from your current IP ---
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=${NAME}-web Name=vpc-id,Values=$VPC --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name ${NAME}-web --description "AUBOT web + admin SSH" --vpc-id "$VPC" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions \
    "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]" \
    "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]" \
    "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP}/32,Description=admin}]" >/dev/null
fi

# --- Encrypted, private S3 bucket for nightly DB backups (kept 30 days) ---
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint="$AWS_REGION" >/dev/null
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
    '{"Rules":[{"ID":"expire-30d","Status":"Enabled","Filter":{"Prefix":"db/"},"Expiration":{"Days":30}}]}'
fi

# --- Instance role: write-only to the backup prefix, plus SSM Session Manager access ---
if ! aws iam get-role --role-name ${NAME}-ec2 >/dev/null 2>&1; then
  aws iam create-role --role-name ${NAME}-ec2 --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name ${NAME}-ec2 --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam put-role-policy --role-name ${NAME}-ec2 --policy-name backup-write --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:PutObject\",\"Resource\":\"arn:aws:s3:::${BUCKET}/db/*\"}]}"
  aws iam create-instance-profile --instance-profile-name ${NAME}-ec2 >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name ${NAME}-ec2 --role-name ${NAME}-ec2
  sleep 10  # IAM propagation
fi

# --- EC2 instance (Amazon Linux 2023, IMDSv2 only, encrypted 20 GB gp3) ---
INSTANCE=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$NAME Name=instance-state-name,Values=pending,running,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$INSTANCE" = "None" ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
  INSTANCE=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --key-name ${NAME}-key \
    --security-group-ids "$SG" --iam-instance-profile Name=${NAME}-ec2 \
    --user-data "file://$HERE/user-data.sh" \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=ITA602-AUBOT}]" \
    --query 'Instances[0].InstanceId' --output text)
fi
aws ec2 wait instance-running --instance-ids "$INSTANCE"

# --- Elastic IP so the address (and HTTPS hostname) survive restarts ---
EIP=$(aws ec2 describe-addresses --filters Name=tag:Name,Values=$NAME --query 'Addresses[0].PublicIp' --output text)
if [ "$EIP" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
  aws ec2 associate-address --instance-id "$INSTANCE" --allocation-id "$ALLOC" >/dev/null
  EIP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)
fi
DOMAIN="$(echo "$EIP" | tr . -).sslip.io"

cat > "$STATE" <<STATE_EOF
REGION=$AWS_REGION
INSTANCE=$INSTANCE
IP=$EIP
DOMAIN=$DOMAIN
BUCKET=$BUCKET
SG=$SG
KEY_FILE=$KEY_FILE
STATE_EOF
echo "Provisioned: https://$DOMAIN  (instance $INSTANCE, $INSTANCE_TYPE)"
