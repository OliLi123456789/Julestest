# modules/ecs_fargate_cluster/variables.tf
variable "environment_name" {
  description = "Name of the environment (e.g., staging, production)."
  type        = string
}

variable "cluster_name" {
  description = "Name for the ECS cluster."
  type        = string
  default     = "" # If empty, will be derived from environment_name
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}
