# modules/ecr_repository/main.tf
resource "aws_ecr_repository" "main" {
  name                 = var.repository_name
  image_tag_mutability = var.image_tag_mutability
  force_delete         = var.force_delete

  image_scanning_configuration {
    scan_on_push = var.enable_scan_on_push
  }

  tags = merge(var.common_tags, {
    Name = var.repository_name
  })
}
