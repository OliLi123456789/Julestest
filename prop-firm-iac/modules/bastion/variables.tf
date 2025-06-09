# modules/bastion/variables.tf

variable "environment_name" {
  description = "Name of the environment (e.g., staging, production)."
  type        = string
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "ID of the VPC where the bastion host will be deployed."
  type        = string
}

variable "public_subnet_id" {
  description = "ID of a public subnet to deploy the bastion host in. For HA, this could be a list and the main.tf would loop or select one."
  type        = string
}

variable "bastion_sg_id" {
  description = "ID of the Security Group for the bastion host (created in the security module)."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for the bastion host."
  type        = string
  default     = "t3.micro" # Or t4g.micro for Graviton - cost-effective
}

variable "ami_id" {
  description = "AMI ID for the bastion host (e.g., latest Amazon Linux 2 or Ubuntu LTS). Ensure it's hardened and has SSM agent."
  type        = string
  # This should be selected based on region and desired OS, typically passed from root module using a data source.
}

variable "key_name" {
  description = "Name of an existing EC2 KeyPair to enable SSH access to the instance if direct SSH is used."
  type        = string
  # Users will use their private key corresponding to this KeyPair.
  # Consider making this optional if SSM Session Manager is the primary access method.
  default     = null
}

variable "enable_detailed_monitoring" {
  description = "Enable detailed CloudWatch monitoring for the bastion instance."
  type        = bool
  default     = true
}

variable "iam_instance_profile_name" {
  description = "Name of the IAM instance profile to attach to the bastion host (e.g., for SSM access, CloudWatch Logs agent)."
  type        = string
  default     = null # A specific role with minimal permissions (SSM, CW Logs) is highly recommended.
}

variable "user_data_script" {
  description = "User data script for bastion host setup (e.g., installing MFA tools, configuring session logging)."
  type        = string
  default     = null # Script content can be passed in or sourced from a file.
}
