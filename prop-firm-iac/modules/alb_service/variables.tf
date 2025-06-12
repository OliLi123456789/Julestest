# modules/alb_service/variables.tf
variable "environment_name" {
  description = "Name of the environment."
  type        = string
}

variable "common_tags" {
  description = "Common tags to apply."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "ID of the VPC where the ALB will be deployed."
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for the ALB."
  type        = list(string)
}

variable "alb_name_prefix" {
  description = "Prefix for the ALB name (e.g., 'api', 'app'). Will be combined with environment."
  type        = string
  default     = "app"
}

variable "internal_alb" {
  description = "Set to true if the ALB should be internal."
  type        = bool
  default     = false
}

variable "enable_https" {
  description = "Set to true to enable HTTPS listener and HTTP to HTTPS redirect."
  type        = bool
  default     = true
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for the HTTPS listener. Required if enable_https is true."
  type        = string
  default     = "" # Must be provided if enable_https is true
}

variable "hosted_zone_name" {
  description = "The name of the Route 53 hosted zone (e.g., myapp.com) to create DNS records in."
  type        = string
  default     = "" # Must be provided for DNS record creation
}

variable "dns_record_name" {
  description = "The DNS record name (e.g., api.myapp.com or staging.api.myapp.com)."
  type        = string
  default     = "" # Must be provided for DNS record creation
}

variable "alb_security_group_ingress_cidrs" {
  description = "List of CIDR blocks to allow ingress traffic to ALB (e.g., ['0.0.0.0/0'] for public)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "health_check_path" {
  description = "Default health check path for the target group."
  type        = string
  default     = "/"
}

variable "health_check_port" {
  description = "Default health check port for the target group."
  type        = string
  default     = "traffic-port"
}
