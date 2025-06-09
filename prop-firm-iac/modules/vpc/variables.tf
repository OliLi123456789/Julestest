# modules/vpc/variables.tf

variable "aws_region" {
  description = "AWS region for the VPC."
  type        = string
}

variable "environment_name" {
  description = "Name of the environment (e.g., staging, production) for tagging."
  type        = string
}

variable "vpc_cidr_block" {
  description = "The CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "A list of Availability Zones to deploy private and public subnets."
  type        = list(string)
  # Example: ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "public_subnet_cidrs" {
  description = "A list of CIDR blocks for public subnets. Must match the number of AZs."
  type        = list(string)
  # Example: ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_app_subnet_cidrs" {
  description = "A list of CIDR blocks for private application subnets. Must match the number of AZs."
  type        = list(string)
  # Example: ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "private_data_subnet_cidrs" {
  description = "A list of CIDR blocks for private data subnets. Must match the number of AZs."
  type        = list(string)
  # Example: ["10.0.201.0/24", "10.0.202.0/24", "10.0.203.0/24"]
}

variable "enable_nat_gateway" {
  description = "Set to true to enable NAT gateway for private subnets. Recommended for production."
  type        = bool
  default     = true
}

variable "single_nat_gateway" {
  description = "Set to true to deploy a single NAT Gateway (cost saving). False for one NAT GW per AZ (HA)."
  type        = bool
  default     = false # Production default should be HA (one per AZ)
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}
