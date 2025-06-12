# modules/iam_service_role/variables.tf
variable "role_name_prefix" {
  description = "Prefix for the IAM role name. Will be combined with environment and service name."
  type        = string
  default     = "service"
}
variable "environment_name" {
  description = "Name of the environment (e.g., staging)."
  type        = string
}
variable "service_name" {
  description = "Name of the service this role is for (e.g., llm-chatbot)."
  type        = string
}
variable "role_description" {
  description = "Description for the IAM role."
  type        = string
  default     = "IAM role for service tasks"
}
variable "assume_role_principals" {
  description = "List of AWS service principals that can assume this role."
  type        = list(string)
  default     = ["ecs-tasks.amazonaws.com"]
}
variable "attach_policy_arns" {
  description = "List of existing IAM policy ARNs to attach to this role."
  type        = list(string)
  default     = []
}
variable "common_tags" {
  description = "Common tags to apply."
  type        = map(string)
  default     = {}
}
