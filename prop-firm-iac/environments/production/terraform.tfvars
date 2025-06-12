# environments/production/terraform.tfvars

aws_region       = "us-east-1" # REPLACE with your primary Production region
# aws_account_id is fetched dynamically by default in main.tf if not set here.
# If you need to hardcode it (e.g., for a different account than where Terraform runs):
# aws_account_id   = "REPLACE_WITH_YOUR_PRODUCTION_AWS_ACCOUNT_ID"

# VPC Variables
vpc_cidr_block          = "10.20.0.0/16" # Example Production VPC CIDR
availability_zones    = ["us-east-1a", "us-east-1b", "us-east-1c"] # Use at least 3 AZs for Production; REPLACE if different region
public_subnet_cidrs   = ["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"] # Ensure these align with availability_zones
private_app_subnet_cidrs = ["10.20.10.0/24", "10.20.11.0/24", "10.20.12.0/24"] # Ensure these align with availability_zones
private_data_subnet_cidrs = ["10.20.20.0/24", "10.20.21.0/24", "10.20.22.0/24"] # Ensure these align with availability_zones
# single_nat_gateway is false by default in production variables.tf (for HA NAT), so no need to set unless overriding to true.

# Security Variables
web_app_port                = 8000 # Default, can be changed if needed
bastion_ingress_ssh_cidrs = ["REPLACE_WITH_YOUR_SECURE_BASTION_ACCESS_IP/32"] # ** REPLACE ** with actual trusted IP for SSH.

# Global IAM Variables
ci_cd_github_org_repo = "YourGitHubOrgName/YourGitHubRepoName" # REPLACE with your GitHub Org/Repo for OIDC (likely same as staging)

# These must match the S3 backend bucket and DynamoDB table (likely same as staging, as key differentiates state)
terraform_state_bucket_name      = "REPLACE_WITH_YOUR_TERRAFORM_STATE_BUCKET_NAME"
terraform_state_lock_table_name  = "REPLACE_WITH_YOUR_TERRAFORM_LOCK_TABLE_NAME"


# S3 Variables
s3_bucket_name_prefix       = "prop-firm" # This will be part of bucket names (likely same as staging)
enable_s3_logging_bucket    = true
enable_s3_cloudtrail_bucket = true
enable_s3_artifacts_bucket  = true
enable_s3_rag_data_bucket   = true    # Create the RAG data bucket in production
# rag_data_force_destroy is false by default in production variables.tf, so no need to set unless overriding to true.

# Monitoring Variables (General CloudTrail)
# cloudtrail_s3_bucket_name is derived from s3_buckets module output
enable_cloudtrail_cloudwatch_logs   = true
# cloudtrail_cloudwatch_log_group_name is defaulted to "/aws/cloudtrail/prop-firm-production-trail" in production variables.tf
# cloudtrail_log_group_retention_days is defaulted to 365 in production variables.tf

# ECS Cluster Variables
ecs_cluster_name = "production-llm-cluster" # Example: Or leave empty "" to use module default "<env>-ecs-cluster"

# ALB & DNS Variables
alb_enable_https        = true # Should always be true for production
alb_acm_certificate_arn = "arn:aws:acm:us-east-1:REPLACE_WITH_YOUR_PROD_ACCOUNT_ID:certificate/REPLACE_WITH_YOUR_PROD_CERTIFICATE_ID" # ** REPLACE **
hosted_zone_name        = "yourdomain.com"  # ** REPLACE ** with your actual Route 53 hosted zone for production
api_alb_dns_name        = "api.yourdomain.com" # ** REPLACE ** with desired DNS name for the API ALB in production

# IAM Role & Policy Variables for LLM Chatbot Service
# llm_secrets_path_prefix is defaulted to "production/llm_chatbot_service/" in production variables.tf
# rag_s3_bucket_arn for the IAM policy is derived from module.s3_buckets.rag_data_bucket_arn

# App Monitoring Variables (for LLM Chatbot Service)
# app_log_retention_days is defaulted to 365 in production variables.tf
alarm_sns_topic_arn    = "arn:aws:sns:us-east-1:REPLACE_WITH_YOUR_PROD_ACCOUNT_ID:YourProductionAlarmsSNSTopicName" # ** REPLACE **
# llm_chatbot_ecs_service_name is defaulted to "llm-chatbot-service-production" in production variables.tf. Update if actual name differs.

# common_tags are defaulted in production variables.tf. Environment is "production".
# Override common_tags if specific additions for production are needed:
# common_tags = {
#   Terraform   = "true"
#   Environment = "production"
#   Project     = "PropFirmPlatform"
#   CostCenter  = "production-main" # Example of adding more specific tag
# }
