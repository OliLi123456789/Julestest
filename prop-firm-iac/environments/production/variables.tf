# environments/production/variables.tf

variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
}

variable "environment_name" {
  description = "The name of the environment (e.g., staging, production)."
  type        = string
  default     = "production" # Changed default for production
}

# Placeholder for variables needed by modules. These will be largely the same
# as in staging's variables.tf, but their values will be set in production.tfvars.
# Example:
# variable "vpc_cidr_block" {
#   description = "The CIDR block for the VPC."
#   type        = string
# }
#
# variable "public_subnet_cidrs" {
#   description = "List of CIDR blocks for public subnets."
#   type        = list(string)
# }
#
# variable "private_app_subnet_cidrs" {
#   description = "List of CIDR blocks for private application subnets."
#   type        = list(string)
# }
#
# variable "private_data_subnet_cidrs" {
#   description = "List of CIDR blocks for private data subnets."
#   type        = list(string)
# }
#
# variable "availability_zones" {
#   description = "List of availability zones to use."
#   type        = list(string)
# }

# More variables will be added as modules are defined. Values for these will
# be provided in production.tfvars or via CI/CD environment variables.
