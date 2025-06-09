# environments/staging/terraform.tfvars

aws_region       = "us-east-1" # REPLACE with your desired Staging region
# aws_account_id is fetched dynamically by default in main.tf if not set here.
# If you need to hardcode it for some reason:
# aws_account_id   = "123456789012" # REPLACE with your actual AWS Account ID

# VPC Variables
vpc_cidr_block          = "10.10.0.0/16" # Staging VPC CIDR
availability_zones    = ["us-east-1a", "us-east-1b"] # Use at least 2 AZs for Staging
public_subnet_cidrs   = ["10.10.1.0/24", "10.10.2.0/24"]
private_app_subnet_cidrs = ["10.10.10.0/24", "10.10.11.0/24"]
private_data_subnet_cidrs = ["10.10.20.0/24", "10.10.21.0/24"]
single_nat_gateway    = true # For Staging, set to true to save cost. Module default is false (HA).

# Security Variables
bastion_ingress_ssh_cidrs = ["YOUR_VPN_OR_OFFICE_IP/32"] # REPLACE with actual trusted IP. DO NOT USE 0.0.0.0/0 for bastion.

# Global IAM Variables
ci_cd_github_org_repo = "YourGitHubOrgName/prop-firm-iac" # REPLACE with your GitHub Org/Repo

# These must match the S3 backend bucket and DynamoDB table created in Sub-step 1.1
terraform_state_bucket_name      = "prop-firm-terraform-state-<YOUR_AWS_ACCOUNT_ID>-<YOUR_REGION>" # REPLACE
terraform_state_lock_table_name  = "prop-firm-terraform-state-lock" # REPLACE (if different from module default)


# S3 Variables
s3_bucket_name_prefix = "prop-firm" # Results in prop-firm-access-logs-staging-ACCOUNTID etc.

# Monitoring Variables
# cloudtrail_cloudwatch_log_group_name is defaulted in variables.tf, override if needed:
# cloudtrail_cloudwatch_log_group_name = "/aws/cloudtrail/custom-staging-trail"
# cloudtrail_log_group_retention_days is defaulted in variables.tf, override if needed:
# cloudtrail_log_group_retention_days = 60

# common_tags are defaulted in variables.tf. Environment is "staging".
# Override common_tags if specific additions for staging are needed:
# common_tags = {
#   Terraform   = "true"
#   Environment = "staging"
#   Project     = "PropFirmPlatform"
#   CostCenter  = "staging-research"
# }
