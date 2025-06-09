# environments/staging/main.tf

provider "aws" {
  region = var.aws_region
  # AWS credentials are expected to be configured via environment variables,
  # shared credentials file, or IAM roles for EC2/ECS when run by CI/CD.
}

# Data source to get AWS Account ID dynamically
data "aws_caller_identity" "current" {}

# Backend configuration should be in backend.tf as per previous step.
# If not, it would be here:
# terraform {
#   backend "s3" {
#     bucket         = "prop-firm-terraform-state-..." # Actual name
#     key            = "environments/staging/terraform.tfstate"
#     region         = "..."                           # Actual region
#     dynamodb_table = "prop-firm-terraform-state-lock" # Actual name
#     encrypt        = true
#   }
# }

# --- Global IAM Module (OIDC Provider, CI/CD Role, Admin/Dev Groups) ---
# This module creates resources that are global or foundational.
# It's called here. In a multi-account setup, it might be managed in a separate AWS account.
# Ensure the OIDC provider for GitHub is created only once per account (manual or separate TF state).
module "global_iam" {
  source = "../../global/iam" # Path to the global IAM module

  aws_account_id                = data.aws_caller_identity.current.account_id
  ci_cd_github_org_repo         = var.ci_cd_github_org_repo
  common_tags                   = var.common_tags
  terraform_state_bucket_name   = var.terraform_state_bucket_name # Pass the specific name
  terraform_state_lock_table_name = var.terraform_state_lock_table_name # Pass the specific name
  aws_region                    = var.aws_region # For constructing ARNs if needed
}

# --- S3 Buckets Module ---
module "s3_buckets" {
  source = "../../modules/s3"

  bucket_name_prefix        = var.s3_bucket_name_prefix
  environment_name          = var.environment_name
  aws_account_id            = data.aws_caller_identity.current.account_id
  common_tags               = var.common_tags
  enable_logging_bucket     = var.enable_s3_logging_bucket
  enable_cloudtrail_bucket  = var.enable_s3_cloudtrail_bucket
  enable_artifacts_bucket   = var.enable_s3_artifacts_bucket
  force_destroy_buckets     = true # For staging, can set to true. For prod, should be false.
  versioning_enabled        = true # Defaulted in module, can be overridden
}

# --- VPC Module ---
module "vpc" {
  source = "../../modules/vpc"

  aws_region                = var.aws_region
  environment_name          = var.environment_name
  vpc_cidr_block            = var.vpc_cidr_block
  availability_zones        = var.availability_zones
  public_subnet_cidrs       = var.public_subnet_cidrs
  private_app_subnet_cidrs  = var.private_app_subnet_cidrs
  private_data_subnet_cidrs = var.private_data_subnet_cidrs
  enable_nat_gateway        = var.enable_nat_gateway
  single_nat_gateway        = var.single_nat_gateway
  common_tags               = var.common_tags
}

# --- Security Module (Security Groups & NACLs) ---
module "security" {
  source = "../../modules/security"

  vpc_id                      = module.vpc.vpc_id # Dependency on VPC module
  vpc_cidr_block              = module.vpc.vpc_cidr_block # Pass VPC CIDR for SG/NACL rules
  environment_name            = var.environment_name
  common_tags                 = var.common_tags
  bastion_ingress_ssh_cidrs   = var.bastion_ingress_ssh_cidrs
  web_app_port                = var.web_app_port
  # app_tier_internal_port is defaulted in module
  # db_port_postgresql is defaulted in module

  # Pass subnet IDs from VPC module to Security module for NACL association
  public_subnet_ids_for_nacl   = module.vpc.public_subnet_ids
  private_app_subnet_ids_for_nacl = module.vpc.private_app_subnet_ids
  private_data_subnet_ids_for_nacl = module.vpc.private_data_subnet_ids
}

# --- Monitoring Module (CloudTrail) ---
module "monitoring" {
  source = "../../modules/monitoring"

  environment_name                    = var.environment_name
  common_tags                         = var.common_tags
  cloudtrail_s3_bucket_name           = module.s3_buckets.cloudtrail_bucket_id # Use output from s3_buckets module (ID is bucket name)
  # cloudtrail_s3_key_prefix          = "AWSLogs/${data.aws_caller_identity.current.account_id}/cloudtrail" # Example prefix

  enable_cloudtrail_cloudwatch_logs   = var.enable_cloudtrail_cloudwatch_logs
  cloudtrail_cloudwatch_log_group_name = var.cloudtrail_cloudwatch_log_group_name
  cloudtrail_log_group_retention_days = var.cloudtrail_log_group_retention_days
  # alarm_sns_topic_arn               = null # Set if you have an SNS topic for alarms
}

# More modules (compute, database, EKS, etc.) will be called here later.
