# modules/security/variables.tf

variable "vpc_id" {
  description = "The ID of the VPC where security groups will be created."
  type        = string
}

variable "environment_name" {
  description = "Name of the environment (e.g., staging, production) for tagging."
  type        = string
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "bastion_ingress_ssh_cidrs" {
  description = "List of CIDR blocks allowed for SSH access to the bastion host."
  type        = list(string)
  default     = ["0.0.0.0/0"] # WARNING: Should be restricted in production.tfvars
}

# Variables for specific tier CIDRs, if needed for SG rules (e.g. if not using SG IDs directly)
variable "vpc_cidr_block" {
  description = "The CIDR block of the VPC, used for some NACL rules or broad internal SG rules."
  type        = string
}

# Input variables for subnet IDs to associate with NACLs
variable "public_subnet_ids_for_nacl" {
  description = "List of public subnet IDs to associate with the public NACL."
  type        = list(string)
  default     = []
}

variable "private_app_subnet_ids_for_nacl" {
  description = "List of private app subnet IDs to associate with the private app NACL."
  type        = list(string)
  default     = []
}

variable "private_data_subnet_ids_for_nacl" {
  description = "List of private data subnet IDs to associate with the private data NACL."
  type        = list(string)
  default     = []
}


# Ports for services
variable "web_app_port" {
  description = "The port the web application tier listens on (e.g., for traffic from ALB)."
  type        = number
  default     = 8000 # Example for a Python web app like FastAPI
}

variable "app_tier_internal_port" {
  description = "An example internal port for app tier services if they communicate with each other directly."
  type        = number
  default     = 8080
}

variable "db_port_postgresql" {
  description = "The port for PostgreSQL database."
  type        = number
  default     = 5432
}
