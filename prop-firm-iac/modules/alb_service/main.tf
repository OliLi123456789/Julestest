# modules/alb_service/main.tf
locals {
  alb_name_final = "${var.environment_name}-${var.alb_name_prefix}-alb"
  # dns_record_name_final will be var.dns_record_name as it should be fully qualified
}

data "aws_route53_zone" "selected" {
  count = var.hosted_zone_name != "" && var.dns_record_name != "" ? 1 : 0
  name  = var.hosted_zone_name
  private_zone = false # Assuming public hosted zones for ALBs
}

resource "aws_security_group" "alb_sg" {
  name        = "${local.alb_name_final}-sg"
  description = "Security group for ${local.alb_name_final}"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.alb_security_group_ingress_cidrs
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.alb_security_group_ingress_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1" # Allow all outbound traffic
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(var.common_tags, { Name = "${local.alb_name_final}-sg" })
}

resource "aws_lb" "main" {
  name               = local.alb_name_final
  internal           = var.internal_alb
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = var.public_subnet_ids # For internet-facing ALB

  enable_deletion_protection = false # Set to true for production

  tags = merge(var.common_tags, { Name = local.alb_name_final })
}

# Default target group - useful for default actions or simple services
# Individual services should ideally create their own specific target groups
resource "aws_lb_target_group" "default" {
  name        = "${local.alb_name_final}-default-tg"
  port        = 80 # Default, can be unused if all rules point elsewhere
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # For Fargate tasks

  health_check {
    path                = var.health_check_path
    port                = var.health_check_port
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
  }
  tags = merge(var.common_tags, { Name = "${local.alb_name_final}-default-tg" })
}

# HTTP Listener
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.enable_https ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = var.enable_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    target_group_arn = var.enable_https ? null : aws_lb_target_group.default.arn
  }
}

# HTTPS Listener
resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08" # Choose a suitable policy
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.default.arn
  }
}

# DNS Record
resource "aws_route53_record" "www" {
  count   = var.hosted_zone_name != "" && var.dns_record_name != "" ? 1 : 0
  zone_id = data.aws_route53_zone.selected[0].zone_id
  name    = var.dns_record_name
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
