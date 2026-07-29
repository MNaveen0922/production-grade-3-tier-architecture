output "instance_id" {
  description = "For `aws ssm start-session --target <this>` instead of SSH"
  value       = aws_instance.sonarqube.id
}

output "public_ip" {
  description = "Stable Elastic IP if enable_elastic_ip=true, otherwise the instance's (changes on stop/start)"
  value       = var.enable_elastic_ip ? aws_eip.sonarqube[0].public_ip : aws_instance.sonarqube.public_ip
}

output "sonarqube_url" {
  description = "This is your SONAR_HOST_URL GitHub Actions secret"
  value       = "http://${var.enable_elastic_ip ? aws_eip.sonarqube[0].public_ip : aws_instance.sonarqube.public_ip}:9000"
}

output "ssm_admin_password_path" {
  description = "Run: aws ssm get-parameter --name <this> --with-decryption --query Parameter.Value --output text"
  value       = "${local.ssm_path_prefix}/admin_password"
}

output "ssm_token_path" {
  description = "This value is your SONAR_TOKEN GitHub Actions secret - fetch with: aws ssm get-parameter --name <this> --with-decryption --query Parameter.Value --output text"
  value       = "${local.ssm_path_prefix}/token"
}

output "private_ip" {
  description = "Private IP of the SonarQube instance - use this (not the public Elastic IP) as SONAR_HOST_URL once CI runs from a self-hosted runner inside the VPC. Avoids public exposure and same-VPC hairpin routing issues."
  value       = aws_instance.sonarqube.private_ip
}

output "sonarqube_private_url" {
  description = "This is the SONAR_HOST_URL value to use once the sonarqube CI job runs on a self-hosted runner inside the VPC"
  value       = "http://${aws_instance.sonarqube.private_ip}:9000"
}