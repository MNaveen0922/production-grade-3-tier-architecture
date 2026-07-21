
terraform {
  backend "s3" {
    bucket       = "naveen-supportdesk-tfstate-2026"
    key          = "enterprise-support/prod/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
}
