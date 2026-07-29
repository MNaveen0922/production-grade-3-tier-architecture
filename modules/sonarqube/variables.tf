variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  description = "VPC to launch the SonarQube instance into"
  type        = string
}

variable "public_subnet_id" {
  description = "Public subnet (needs a route to an IGW) so the instance can pull the Docker images and reach the AWS SSM API"
  type        = string
}

variable "allowed_cidr_blocks" {
  description = "CIDRs allowed to reach the SonarQube UI on port 9000 - set this to your IP (x.x.x.x/32) in terraform.tfvars. Deliberately no default so nobody accidentally opens this to the internet."
  type        = list(string)
}

variable "instance_type" {
  description = "SonarQube + Elasticsearch need at least 2 vCPU / 4GB RAM to boot at all"
  type        = string
  default     = "m7i-flex.large"
}

variable "root_volume_size_gb" {
  description = "SonarQube data + Postgres + Elasticsearch indices live here"
  type        = number
  default     = 30
}

variable "sonar_project_key" {
  description = "Project key auto-created in SonarQube on boot - should match sonar-project.properties"
  type        = string
  default     = "support-desk-platform"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "enable_elastic_ip" {
  description = "Attach a static Elastic IP so SONAR_HOST_URL never changes if the instance restarts"
  type        = bool
  default     = true
}

variable "key_name" {
  description = "Optional EC2 key pair name for SSH fallback. Leave null to rely on SSM Session Manager only (no open port 22, no key to lose)."
  type        = string
  default     = null
}

variable "eks_nodes_security_group_id" {
  description = "Security group ID of the EKS worker nodes - allows the self-hosted CI runner (running as a pod on those nodes) to reach SonarQube privately, without opening port 9000 to the public internet."
  type        = string
}