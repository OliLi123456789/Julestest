# modules/ecr_repository/variables.tf
variable "repository_name" {
  description = "Name of the ECR repository."
  type        = string
}

variable "image_tag_mutability" {
  description = "The tag mutability setting for the repository. Valid values are MUTABLE or IMMUTABLE."
  type        = string
  default     = "IMMUTABLE"
}

variable "enable_scan_on_push" {
  description = "Set to true to enable image scanning on push."
  type        = bool
  default     = true
}

variable "force_delete" {
  description = "If true, will delete the repository even if it contains images. Use with caution."
  type        = bool
  default     = false # Safer default
}

variable "common_tags" {
  description = "Common tags to apply to the repository."
  type        = map(string)
  default     = {}
}
