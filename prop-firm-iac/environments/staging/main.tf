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
  terraform_state_bucket_name   = var.terraform_state_bucket_name
  terraform_state_lock_table_name = var.terraform_state_lock_table_name
  aws_region                    = var.aws_region

  # CI/CD Policy Scoping Variables
  cicd_ecr_repository_arns = [
    module.llm_chatbot_ecr_repo.repository_arn,
    # Add other app ECR repo ARNs here as they are created, e.g.:
    # module.webapp_backend_ecr_repo.repository_arn
  ]
  # For ECS services, initially grant broader permission to update any service in the cluster.
  # This can be refined if specific service ARNs are known or managed differently.
  cicd_ecs_service_arns = [
    "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${module.ecs_cluster.ecs_cluster_name}/*",
  ]
  cicd_iam_passrole_arns = [
    module.llm_chatbot_service_role.role_arn, # Role for LLM service tasks
    module.ecs_cluster.ecs_task_execution_role_arn, # Default task execution role created with ECS cluster
    # Add other specific ECS Task Role ARNs here as they are created
  ]
  # Assuming no frontend S3 bucket or CloudFront distributions are managed by this specific staging config for now
  cicd_frontend_s3_bucket_arns      = []
  cicd_cloudfront_distribution_arns = []
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
  force_destroy_buckets     = true # General flag for artifacts bucket in module
  versioning_enabled        = true # General flag for versioning in module

  # New RAG bucket parameters
  enable_rag_data_bucket    = var.enable_s3_rag_data_bucket
  rag_data_force_destroy    = var.rag_data_force_destroy
  # rag_data_versioning_enabled is defaulted to true in the module
  # rag_data_bucket_name_suffix is defaulted in the module
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

# --- ECS Fargate Cluster Module ---
module "ecs_cluster" {
  source = "../../modules/ecs_fargate_cluster"

  environment_name = var.environment_name
  cluster_name     = var.ecs_cluster_name # Use a variable for cluster name
  common_tags      = var.common_tags
}

# --- ALB for Backend Services ---
module "api_alb" {
  source = "../../modules/alb_service"

  environment_name    = var.environment_name
  common_tags         = var.common_tags
  vpc_id              = module.vpc.vpc_id
  public_subnet_ids   = module.vpc.public_subnet_ids

  alb_name_prefix     = "api" # e.g., staging-api-alb
  enable_https        = var.alb_enable_https
  acm_certificate_arn = var.alb_acm_certificate_arn
  hosted_zone_name    = var.hosted_zone_name # e.g., "staging.propfirm.example.com" or "propfirm-staging.com"
  dns_record_name     = var.api_alb_dns_name # e.g., "api.staging.propfirm.example.com"
  # alb_security_group_ingress_cidrs is defaulted in module to ["0.0.0.0/0"]
}

# --- ECR Repository for LLM Chatbot Service ---
module "llm_chatbot_ecr_repo" {
  source = "../../modules/ecr_repository"

  repository_name = "${var.environment_name}-llm-chatbot-service" # e.g., staging-llm-chatbot-service
  common_tags     = var.common_tags
  # image_tag_mutability and enable_scan_on_push use module defaults (IMMUTABLE, true)
  # force_delete uses module default (false), which is acceptable for staging to prevent accidental deletion.
  # If staging requires frequent clean-up and recreation, this could be set to true via a staging-specific variable.
}

# IAM Policy for LLM Chatbot Service (Secrets Manager & S3 RAG Access)
resource "aws_iam_policy" "llm_chatbot_service_staging_policy" {
  name        = "${var.environment_name}-llm-chatbot-service-policy"
  description = "Policy for LLM Chatbot Service in ${var.environment_name} to access Secrets Manager and S3 RAG bucket."

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action = [
          "secretsmanager:GetSecretValue"
        ],
        Effect   = "Allow",
        # Restrict to specific secrets or paths. Using path-based restriction:
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.llm_secrets_path_prefix}*"
      },
      {
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Effect   = "Allow",
        Resource = [
          module.s3_buckets.rag_data_bucket_arn,
          "${module.s3_buckets.rag_data_bucket_arn}/*"  # Access to objects within the bucket
        ]
      }
      # Add s3:PutObject if the service needs to write back to the RAG bucket
    ]
  })
  tags = merge(var.common_tags, { Name = "${var.environment_name}-llm-chatbot-service-policy" })
}

# --- IAM Role for LLM Chatbot Service ---
module "llm_chatbot_service_role" {
  source = "../../modules/iam_service_role"

  environment_name = var.environment_name
  service_name     = "llm-chatbot" # A short name for the service
  role_description = "IAM role for LLM Chatbot Service tasks in Staging"
  common_tags      = var.common_tags
  attach_policy_arns = [
    aws_iam_policy.llm_chatbot_service_staging_policy.arn
    # Add other general policies if needed, e.g., CloudWatch Logs access if not covered by default Task Execution Role from ecs_fargate_cluster
  ]
  # assume_role_principals defaults to ["ecs-tasks.amazonaws.com"], which is suitable for ECS tasks.
}

# --- App Monitoring for LLM Chatbot Service ---
module "llm_chatbot_monitoring" {
  source = "../../modules/app_monitoring"

  environment_name = var.environment_name
  service_name     = "llm-chatbot" # Logical service name for tagging/naming log group
  common_tags      = var.common_tags

  log_group_name       = "/ecs/${var.environment_name}/llm-chatbot-service" # Example specific name, ensure it's unique
  log_retention_days   = var.app_log_retention_days

  alarm_sns_topic_arn  = var.alarm_sns_topic_arn

  # ALB Alarms
  enable_alb_5xx_alarm          = var.alb_enable_https # Typically enable ALB alarms if HTTPS (and thus ALB) is enabled
  alb_load_balancer_arn_suffix  = module.api_alb.alb_arn_suffix
  alb_target_group_arn_suffix = module.api_alb.default_target_group_arn_suffix # Assuming default TG is used by this service for now

  # ECS Alarms
  enable_ecs_service_cpu_alarm    = true # Explicitly enable or make these configurable per service
  enable_ecs_service_memory_alarm = true
  ecs_cluster_name                = module.ecs_cluster.ecs_cluster_name
  ecs_service_name_for_alarms     = var.llm_chatbot_ecs_service_name

  # Thresholds can be overridden here if needed, else module defaults used.
  # cpu_alarm_threshold_percent = 75
  # memory_alarm_threshold_percent = 75
  # error_rate_alarm_threshold_count = 10 # Count of 5XX errors in 5min to trigger alarm
}


# More modules (compute, database, EKS, etc.) will be called here later.
