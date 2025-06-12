# environments/production/variables.tf

variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  # No default, should be set in production.tfvars
}

variable "aws_account_id" {
  description = "The AWS Account ID. Will be dynamically fetched if not set."
  type        = string
  default     = "" # Allows dynamic fetching via data source if not explicitly set
}

variable "environment_name" {
  description = "The name of the environment."
  type        = string
  default     = "production"
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default = {
    Terraform   = "true"
    Environment = "production" # Changed for production
    Project     = "PropFirmPlatform"
  }
}

# --- VPC Module Variables ---
variable "vpc_cidr_block" {
  description = "The CIDR block for the VPC."
  type        = string
  # No default, should be set in production.tfvars (e.g., "10.20.0.0/16")
}

variable "availability_zones" {
  description = "List of availability zones to use for the VPC."
  type        = list(string)
  # No default, should be set in production.tfvars (e.g., ["us-east-1a", "us-east-1b", "us-east-1c"])
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets. Must match the number of AZs."
  type        = list(string)
  # No default, should be set in production.tfvars
}

variable "private_app_subnet_cidrs" {
  description = "List of CIDR blocks for private application subnets. Must match the number of AZs."
  type        = list(string)
  # No default, should be set in production.tfvars
}

variable "private_data_subnet_cidrs" {
  description = "List of CIDR blocks for private data subnets. Must match the number of AZs."
  type        = list(string)
  # No default, should be set in production.tfvars
}

variable "enable_nat_gateway" {
  description = "Enable NAT gateway for the VPC."
  type        = bool
  default     = true # Typically true for production for outbound access
}

variable "single_nat_gateway" {
  description = "Use a single NAT Gateway for all AZs (cost saving) or one per AZ (HA)."
  type        = bool
  default     = false # Production should use HA NAT Gateways (one per AZ)
}

# --- Security Module Variables ---
variable "bastion_ingress_ssh_cidrs" {
  description = "List of CIDR blocks allowed for SSH access to the bastion host."
  type        = list(string)
  # No default, should be set in production.tfvars with very restricted IPs
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
  # No default, should be set in production.tfvars (likely same as staging)
}

variable "terraform_state_bucket_name" {
  description = "The name of the S3 bucket used for Terraform state."
  type        = string
  # No default, should be set in production.tfvars (same as staging)
}

variable "terraform_state_lock_table_name" {
  description = "The name of the DynamoDB table used for Terraform state locking."
  type        = string
  # No default, should be set in production.tfvars (same as staging)
}

# --- S3 Module Variables ---
variable "s3_bucket_name_prefix" {
  description = "Prefix for S3 bucket names."
  type        = string
  # No default, should be set in production.tfvars (likely same as staging)
}

variable "enable_s3_logging_bucket" {
  description = "Flag to enable creation of S3 access logging bucket."
  type        = bool
  default     = true # Recommended for production
}

variable "enable_s3_cloudtrail_bucket" {
  description = "Flag to enable creation of S3 bucket for CloudTrail."
  type        = bool
  default     = true # Recommended for production
}

variable "enable_s3_artifacts_bucket" {
  description = "Flag to enable creation of S3 bucket for CI/CD artifacts."
  type        = bool
  default     = true # Recommended for production
}

variable "enable_s3_rag_data_bucket" {
  description = "Flag to enable creation of S3 bucket for RAG data."
  type        = bool
  default     = true # Enable RAG bucket for production by default
}

variable "rag_data_force_destroy" {
  description = "Force destroy RAG S3 bucket."
  type        = bool
  default     = false # Production data should not be force destroyed
}

# --- Monitoring Module Variables ---
variable "enable_cloudtrail_cloudwatch_logs" {
  description = "Flag to enable sending CloudTrail logs to CloudWatch Logs."
  type        = bool
  default     = true # Recommended for production
}

variable "cloudtrail_cloudwatch_log_group_name" {
  description = "Name for CloudTrail's CloudWatch Log Group."
  type        = string
  default     = "/aws/cloudtrail/prop-firm-production-trail" # Changed for production
}

variable "cloudtrail_log_group_retention_days" {
  description = "Retention period in days for CloudTrail logs in CloudWatch."
  type        = number
  default     = 365 # Longer retention for production
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
  default     = true # Must be true for production
}
variable "alb_acm_certificate_arn" {
  description = "ACM certificate ARN for the main API ALB HTTPS listener."
  type        = string
  # No default, must be provided in production.tfvars
}
variable "hosted_zone_name" {
  description = "Route 53 hosted zone name for creating DNS records."
  type        = string
  # No default, must be provided in production.tfvars (e.g., "yourdomain.com")
}
variable "api_alb_dns_name" {
  description = "DNS name for the API ALB (e.g., api.yourdomain.com)."
  type        = string
  # No default, must be provided in production.tfvars
}

# --- IAM Service Role specific for LLM Chatbot service ---
variable "llm_secrets_path_prefix" {
  description = "Path prefix for Secrets Manager secrets for the LLM service. Include trailing slash if it's a path."
  type        = string
  default     = "production/llm_chatbot_service/" # Changed for production
}

# --- App Monitoring Module Variables (for LLM Chatbot Service) ---
variable "app_log_retention_days" {
  description = "Number of days to retain application logs (e.g., for llm-chatbot-service)."
  type        = number
  default     = 365 # Longer retention for production logs
}

variable "alarm_sns_topic_arn" {
  description = "ARN of the SNS topic to send CloudWatch alarms to."
  type        = string
  # No default, must be set in production.tfvars
}

variable "llm_chatbot_ecs_service_name" {
  description = "Actual deployed ECS service name for the LLM Chatbot service, used for ECS-specific alarms."
  type        = string
  default     = "llm-chatbot-service-production" # Example, ensure this matches the actual deployed service name
}
