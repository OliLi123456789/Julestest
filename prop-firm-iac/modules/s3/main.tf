# modules/s3/main.tf

locals {
  # Construct unique bucket names - ensuring compliance with S3 naming rules (lowercase, no underscores)
  # Replacing underscores from environment_name if any, and making it lowercase.
  env_name_sanitized = lower(replace(var.environment_name, "_", "-"))
  acc_id_sanitized   = var.aws_account_id # Assuming account ID is already numbers

  logging_bucket_name    = var.enable_logging_bucket ? "${var.bucket_name_prefix}-access-logs-${local.env_name_sanitized}-${local.acc_id_sanitized}" : null
  cloudtrail_bucket_name = var.enable_cloudtrail_bucket ? "${var.bucket_name_prefix}-cloudtrail-${local.env_name_sanitized}-${local.acc_id_sanitized}" : null
  artifacts_bucket_name  = var.enable_artifacts_bucket ? "${var.bucket_name_prefix}-artifacts-${local.env_name_sanitized}-${local.acc_id_sanitized}" : null
}

# --- Centralized Server Access Logging Bucket (Optional) ---
resource "aws_s3_bucket" "logging" {
  count  = var.enable_logging_bucket ? 1 : 0
  bucket = local.logging_bucket_name
  # ACL is deprecated, use aws_s3_bucket_acl if legacy explicit ACLs are needed. Block Public Access is preferred.

  tags = merge(var.common_tags, {
    Name        = local.logging_bucket_name
    Purpose     = "Centralized Server Access Logs"
    Environment = var.environment_name
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logging" {
  count  = var.enable_logging_bucket ? 1 : 0
  bucket = aws_s3_bucket.logging[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logging" {
  count  = var.enable_logging_bucket ? 1 : 0
  bucket = aws_s3_bucket.logging[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "logging" {
  count  = var.enable_logging_bucket && var.versioning_enabled ? 1 : 0
  bucket = aws_s3_bucket.logging[0].id
  versioning_configuration {
    status = "Enabled"
  }
}


# --- CloudTrail S3 Bucket (Optional) ---
resource "aws_s3_bucket" "cloudtrail" {
  count  = var.enable_cloudtrail_bucket ? 1 : 0
  bucket = local.cloudtrail_bucket_name

  tags = merge(var.common_tags, {
    Name        = local.cloudtrail_bucket_name
    Purpose     = "CloudTrail Logs"
    Environment = var.environment_name
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  count  = var.enable_cloudtrail_bucket ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  count  = var.enable_cloudtrail_bucket ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "cloudtrail" {
  count  = var.enable_cloudtrail_bucket && var.versioning_enabled ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

# Policy for CloudTrail to write to this bucket
data "aws_iam_policy_document" "cloudtrail_s3_policy_doc" {
  count = var.enable_cloudtrail_bucket ? 1 : 0
  statement {
    sid       = "AWSCloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail[0].arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
  }
  statement {
    sid       = "AWSCloudTrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail[0].arn}/AWSLogs/${var.aws_account_id}/*"] # Ensure var.aws_account_id is correctly passed
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  count  = var.enable_cloudtrail_bucket ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  policy = data.aws_iam_policy_document.cloudtrail_s3_policy_doc[0].json
}


# --- CI/CD Artifacts S3 Bucket (Optional) ---
resource "aws_s3_bucket" "artifacts" {
  count         = var.enable_artifacts_bucket ? 1 : 0
  bucket        = local.artifacts_bucket_name
  force_destroy = var.force_destroy_buckets # Useful for ephemeral dev/test artifacts

  tags = merge(var.common_tags, {
    Name        = local.artifacts_bucket_name
    Purpose     = "CI/CD Artifacts"
    Environment = var.environment_name
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  count  = var.enable_artifacts_bucket ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  count  = var.enable_artifacts_bucket ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  count  = var.enable_artifacts_bucket && var.versioning_enabled ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  count  = var.enable_artifacts_bucket ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id

  rule {
    id     = "expire-old-artifacts"
    status = "Enabled"
    expiration {
      days = 30 # Example: expire artifacts older than 30 days
    }
    # Can also add noncurrent_version_expiration for versioned buckets
    noncurrent_version_expiration {
      noncurrent_days = 7 # Example: expire non-current versions after 7 days
    }
  }
}
