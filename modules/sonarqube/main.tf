data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# The AWS-managed KMS key SSM SecureString parameters use by default -
# the instance role needs explicit permission to use it.
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}


resource "aws_security_group" "sonarqube" {
  name_prefix = "${var.project_name}-${var.environment}-sonarqube-"
  description = "SonarQube UI access - restricted to allowed_cidr_blocks, no open SSH (use SSM Session Manager)"
  vpc_id      = var.vpc_id

  ingress {
    description = "SonarQube UI"
    from_port   = 9000
    to_port     = 9000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  dynamic "ingress" {
    for_each = var.key_name != null ? [1] : []
    content {
      description = "SSH fallback - only opened when key_name is set"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidr_blocks
    }
  }

  egress {
    description = "Docker image pulls, AWS API calls (SSM, etc.)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-sonarqube-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}


resource "aws_iam_role" "sonarqube_ec2" {
  name = "${var.project_name}-${var.environment}-sonarqube-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Lets you `aws ssm start-session --target <instance-id>` instead of SSH -
# no key pair, no open port 22, no bastion host needed.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.sonarqube_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "sonarqube_ssm_write" {
  name = "${var.project_name}-${var.environment}-sonarqube-ssm-write"
  role = aws_iam_role.sonarqube_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ssm:PutParameter", "ssm:GetParameter"]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:*:parameter${local.ssm_path_prefix}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = [data.aws_kms_alias.ssm.target_key_arn]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "sonarqube" {
  name = "${var.project_name}-${var.environment}-sonarqube-profile"
  role = aws_iam_role.sonarqube_ec2.name
}


locals {
  ssm_path_prefix = "/${var.project_name}/${var.environment}/sonarqube"
}


resource "aws_instance" "sonarqube" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  subnet_id                   = var.public_subnet_id
  vpc_security_group_ids      = [aws_security_group.sonarqube.id]
  iam_instance_profile        = aws_iam_instance_profile.sonarqube.name
  key_name                    = var.key_name
  associate_public_ip_address = true

  root_block_device {
    volume_size           = var.root_volume_size_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tpl", {
    sonar_project_key = var.sonar_project_key
    aws_region        = var.aws_region
    ssm_path_prefix   = local.ssm_path_prefix
  })

  # Re-running user_data requires a replace, which is what we want here:
  # any change to the boot script should rebuild the box cleanly rather
  # than leaving a half-configured instance behind.
  user_data_replace_on_change = true

  tags = {
    Name = "${var.project_name}-${var.environment}-sonarqube"
  }
}


resource "aws_eip" "sonarqube" {
  count    = var.enable_elastic_ip ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.sonarqube.id

  tags = {
    Name = "${var.project_name}-${var.environment}-sonarqube-eip"
  }
}
