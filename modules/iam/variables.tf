variable "project_name" {
  description = "Prefix for all IAM resource names, e.g. 'enterprise-support'"
  type        = string
}

variable "environment" {
  description = "Environment name, e.g. 'prod'"
  type        = string
}
