# environments/staging/variables.tf

variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
}

variable "aws_account_id" {
  description = "The AWS Account ID. Will be dynamically fetched if not set."
  type        = string
  default     = "" # Allows dynamic fetching via data source if not explicitly set
}

variable "environment_name" {
  description = "The name of the environment (e.g., staging, production)."
  type        = string
  default     = "staging"
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default = {
    Terraform   = "true"
    Environment = "staging"
    Project     = "PropFirmPlatform"
  }
}

# --- VPC Module Variables ---
variable "vpc_cidr_block" {
  description = "The CIDR block for the VPC."
  type        = string
}

variable "availability_zones" {
  description = "List of availability zones to use for the VPC."
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets. Must match the number of AZs."
  type        = list(string)
}

variable "private_app_subnet_cidrs" {
  description = "List of CIDR blocks for private application subnets. Must match the number of AZs."
  type        = list(string)
}

variable "private_data_subnet_cidrs" {
  description = "List of CIDR blocks for private data subnets. Must match the number of AZs."
  type        = list(string)
}

variable "enable_nat_gateway" {
  description = "Enable NAT gateway for the VPC."
  type        = bool
  default     = true
}

variable "single_nat_gateway" {
  description = "Use a single NAT Gateway for all AZs (cost saving) or one per AZ (HA)."
  type        = bool
  default     = false
}

# --- Security Module Variables ---
variable "bastion_ingress_ssh_cidrs" {
  description = "List of CIDR blocks allowed for SSH access to the bastion host."
  type        = list(string)
}

variable "web_app_port" {
  description = "Port for the web application tier."
  type        = number
  default     = 8000
}

# --- Global IAM Module Variables ---
variable "ci_cd_github_org_repo" {
  description = "GitHub Org/Repo slug for OIDC trust (e.g., 'MyOrg/prop-firm-iac')."
  type        = string
}

# These are needed by global_iam module for its CI/CD policy to access state backend
variable "terraform_state_bucket_name" {
  description = "The name of the S3 bucket used for Terraform state."
  type        = string
}

variable "terraform_state_lock_table_name" {
  description = "The name of the DynamoDB table used for Terraform state locking."
  type        = string
}

# --- S3 Module Variables ---
variable "s3_bucket_name_prefix" {
  description = "Prefix for S3 bucket names."
  type        = string
}

variable "enable_s3_logging_bucket" {
  description = "Flag to enable creation of S3 access logging bucket."
  type        = bool
  default     = true
}

variable "enable_s3_cloudtrail_bucket" {
  description = "Flag to enable creation of S3 bucket for CloudTrail."
  type        = bool
  default     = true
}

variable "enable_s3_artifacts_bucket" {
  description = "Flag to enable creation of S3 bucket for CI/CD artifacts."
  type        = bool
  default     = true
}

variable "enable_s3_rag_data_bucket" {
  description = "Flag to enable creation of S3 bucket for RAG data."
  type        = bool
  default     = true # Enable RAG bucket for staging by default
}

variable "rag_data_force_destroy" {
  description = "Force destroy RAG S3 bucket in staging (useful for ephemeral test data)."
  type        = bool
  default     = true # OK for staging
}

# --- Monitoring Module Variables ---
# cloudtrail_s3_bucket_name will be derived from s3 module output
variable "enable_cloudtrail_cloudwatch_logs" {
  description = "Flag to enable sending CloudTrail logs to CloudWatch Logs."
  type        = bool
  default     = true
}

variable "cloudtrail_cloudwatch_log_group_name" {
  description = "Name for CloudTrail's CloudWatch Log Group."
  type        = string
  default     = "/aws/cloudtrail/prop-firm-staging-trail"
}

variable "cloudtrail_log_group_retention_days" {
  description = "Retention period in days for CloudTrail logs in CloudWatch."
  type        = number
  default     = 90
}

# --- ECS Cluster Module Variables ---
variable "ecs_cluster_name" {
  description = "Name for the ECS cluster in this environment."
  type        = string
  default     = "" # Allows module to derive from environment_name if not set
}

# --- ALB Service Module Variables ---
variable "alb_enable_https" {
  description = "Enable HTTPS for the main API ALB."
  type        = bool
  default     = true
}
variable "alb_acm_certificate_arn" {
  description = "ACM certificate ARN for the main API ALB HTTPS listener."
  type        = string
  default     = "" # Must be provided if alb_enable_https is true
}
variable "hosted_zone_name" {
  description = "Route 53 hosted zone name for creating DNS records."
  type        = string
  default     = "" # e.g., "staging.propfirm.example.com"
}
variable "api_alb_dns_name" {
  description = "DNS name for the API ALB (e.g., api.staging.propfirm.example.com)."
  type        = string
  default     = ""
}

# --- IAM Service Role specific for LLM Chatbot service ---
variable "llm_secrets_path_prefix" {
  description = "Path prefix for Secrets Manager secrets for the LLM service (e.g., 'staging/llm_chatbot_service/'). Include trailing slash if it's a path."
  type        = string
  default     = "staging/llm_chatbot_service/" # Example
}
# rag_s3_bucket_arn is now sourced from module "s3_buckets" output, so no variable here.
