# environments/staging/terraform.tfvars

aws_region       = "us-east-1" # REPLACE with your desired Staging region
# aws_account_id is fetched dynamically by default in main.tf if not set here.
# If you need to hardcode it for some reason:
# aws_account_id   = "123456789012" # REPLACE with your actual AWS Account ID

# VPC Variables
vpc_cidr_block          = "10.10.0.0/16"
availability_zones    = ["us-east-1a", "us-east-1b"] # REPLACE with your desired AZs for Staging (at least 2)
public_subnet_cidrs   = ["10.10.1.0/24", "10.10.2.0/24"] # Ensure these align with availability_zones
private_app_subnet_cidrs = ["10.10.10.0/24", "10.10.11.0/24"] # Ensure these align with availability_zones
private_data_subnet_cidrs = ["10.10.20.0/24", "10.10.21.0/24"] # Ensure these align with availability_zones
single_nat_gateway    = true # For Staging, true saves cost. Set to false for HA NAT.

# Security Variables
web_app_port                = 8000 # Default, can be changed if needed
bastion_ingress_ssh_cidrs = ["YOUR_HOME_OR_OFFICE_IP/32"] # REPLACE with actual trusted IP for SSH. DO NOT USE 0.0.0.0/0.

# Global IAM Variables
ci_cd_github_org_repo = "YourGitHubOrgName/YourGitHubRepoName" # REPLACE with your GitHub Org/Repo for OIDC

# These must match the S3 backend bucket and DynamoDB table created in Sub-step 1.1
terraform_state_bucket_name      = "REPLACE_WITH_YOUR_TERRAFORM_STATE_BUCKET_NAME"
terraform_state_lock_table_name  = "REPLACE_WITH_YOUR_TERRAFORM_LOCK_TABLE_NAME"


# S3 Variables
s3_bucket_name_prefix       = "prop-firm" # This will be part of bucket names
enable_s3_logging_bucket    = true
enable_s3_cloudtrail_bucket = true
enable_s3_artifacts_bucket  = true
enable_s3_rag_data_bucket   = true    # Create the RAG data bucket in staging
rag_data_force_destroy    = true    # OK for staging to allow destroy on non-empty RAG bucket

# Monitoring Variables (General CloudTrail)
# cloudtrail_s3_bucket_name is derived from s3_buckets module output
enable_cloudtrail_cloudwatch_logs   = true
cloudtrail_cloudwatch_log_group_name = "/aws/cloudtrail/prop-firm-staging-trail" # Default, or customize
cloudtrail_log_group_retention_days = 90 # Default, or customize

# ECS Cluster Variables
ecs_cluster_name = "staging-llm-cluster" # Example: Or leave empty "" to use module default "<env>-ecs-cluster"

# ALB & DNS Variables
alb_enable_https        = true
alb_acm_certificate_arn = "arn:aws:acm:us-east-1:REPLACE_WITH_YOUR_ACCOUNT_ID:certificate/REPLACE_WITH_YOUR_CERTIFICATE_ID" # ** REPLACE **
hosted_zone_name        = "staging.yourdomain.com"  # ** REPLACE ** with your actual Route 53 hosted zone for staging
api_alb_dns_name        = "api.staging.yourdomain.com" # ** REPLACE ** with desired DNS name for the API ALB

# IAM Role & Policy Variables for LLM Chatbot Service
llm_secrets_path_prefix = "staging/llm-chatbot-service/" # Default, ensure this matches your secret naming in AWS Secrets Manager
# rag_s3_bucket_arn for the IAM policy is derived from module.s3_buckets.rag_data_bucket_arn

# App Monitoring Variables (for LLM Chatbot Service)
app_log_retention_days = 30 # Default, or customize for LLM service logs
alarm_sns_topic_arn    = "arn:aws:sns:us-east-1:REPLACE_WITH_YOUR_ACCOUNT_ID:YourAlarmsSNSTopicName" # ** REPLACE ** with your actual SNS topic ARN for alarms
llm_chatbot_ecs_service_name = "llm-chatbot-service-staging" # REPLACE if your actual deployed ECS service name for the LLM app will be different

# common_tags are defaulted in variables.tf. Environment is "staging".
# Override common_tags if specific additions for staging are needed:
# common_tags = {
#   Terraform   = "true"
#   Environment = "staging"
#   Project     = "PropFirmPlatform"
#   CostCenter  = "staging-research-dev" # Example of adding more specific tag
# }
