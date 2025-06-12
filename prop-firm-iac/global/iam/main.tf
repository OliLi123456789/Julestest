# global/iam/main.tf

# --- Conceptual AWS SSO Setup ---
# Terraform cannot fully manage AWS SSO setup. This is typically done via the AWS Console.
# However, you can manage permission sets and assignments if AWS SSO is already enabled.
# For this module, we'll note it as the recommended approach for user management.
# If AWS SSO is used, IAM users and groups below might not be necessary for human access.

# --- IAM Groups (if not primarily using AWS SSO for human users) ---
resource "aws_iam_group" "administrators" {
  name = var.admin_group_name
  # path = "/users/" # Optional path
}

resource "aws_iam_group" "developers" {
  name = var.developer_group_name
  # path = "/users/" # Optional path
}

# --- IAM Policies for Groups ---
# Administrator Access Policy
resource "aws_iam_policy" "administrator_access" {
  name        = "AdministratorAccessPolicy"
  description = "Policy granting full administrator access."
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = "*",
        Resource = "*"
      }
    ]
  })
  tags = var.common_tags
}

# Developer Access Policy (Example - more restrictive, customize as needed)
resource "aws_iam_policy" "developer_access" {
  name        = "DeveloperAccessPolicy"
  description = "Policy granting access for developers."
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "ec2:Describe*",
          "rds:Describe*",
          "s3:ListBucket",
          "s3:GetObject",
          # Add more read-only and specific development permissions
          "iam:GetAccountPasswordPolicy",
          "iam:GetAccountSummary",
          "iam:ListAccountAliases",
          "iam:ListUsers",
          "iam:GetUser",
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:UpdateAccessKey",
          "iam:ListAccessKeys",
          "iam:CreateVirtualMFADevice",
          "iam:EnableMFADevice",
          "iam:ListMFADevices",
          "iam:ResyncMFADevice",
          "iam:DeleteVirtualMFADevice"
        ],
        Resource = "*"
      }
      # Example: Allow specific S3 bucket actions for dev artifacts
      # {
      #   Effect = "Allow",
      #   Action = [
      #     "s3:PutObject",
      #     "s3:GetObject",
      #     "s3:DeleteObject"
      #   ],
      #   Resource = "arn:aws:s3:::your-dev-artifact-bucket/*"
      # }
    ]
  })
  tags = var.common_tags
}

# Attach policies to groups
resource "aws_iam_group_policy_attachment" "admin_attach" {
  group      = aws_iam_group.administrators.name
  policy_arn = aws_iam_policy.administrator_access.arn
}

resource "aws_iam_group_policy_attachment" "developer_attach" {
  group      = aws_iam_group.developers.name
  policy_arn = aws_iam_policy.developer_access.arn
}

# --- CI/CD IAM Role for GitHub Actions (OIDC) ---
data "aws_iam_policy_document" "github_oidc_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"
    principals {
      type        = "Federated"
      identifiers = ["arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.ci_cd_github_org_repo}:*"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cicd_github_actions" {
  name                 = "CICDGitHubActionsRole"
  description          = "IAM Role for GitHub Actions CI/CD pipelines to manage AWS resources."
  assume_role_policy   = data.aws_iam_policy_document.github_oidc_assume_role_policy.json
  max_session_duration = 3600 # 1 hour

  tags = var.common_tags
}

# --- IAM Policy for CI/CD Role (Application Deployment Focus) ---
resource "aws_iam_policy" "cicd_permissions" {
  name        = "CICDApplicationDeploymentPolicy" # More specific name
  description = "Policy for CI/CD role to deploy applications (ECR, ECS, S3 for frontend)."
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      // ECR permissions
      {
        Effect = "Allow",
        Action = [
          "ecr:GetAuthorizationToken"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetRepositoryPolicy",
          # "ecr:DescribeRepositories", // General describe is separate, more permissive
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage"
        ],
        Resource = var.cicd_ecr_repository_arns # Scoped to specific ECR repositories
      },
      // Allow describing ECR repositories (general, needed for some CI tools to list/check repos)
      {
        Effect   = "Allow",
        Action   = "ecr:DescribeRepositories",
        Resource = "*"
      },
      // ECS permissions
      {
        Effect = "Allow",
        Action = [
          "ecs:RegisterTaskDefinition",
          "ecs:DescribeTaskDefinition"
        ],
        Resource = "*" // Task Definition ARNs are not known beforehand, can be scoped by family prefix if desired
                       // e.g., "arn:aws:ecs:REGION:ACCOUNT_ID:task-definition/my-service-family-prefix-*:*"
      },
      {
        Effect = "Allow",
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:ListTasks",
          "ecs:DescribeTasks"
        ],
        Resource = var.cicd_ecs_service_arns # Scoped to specific ECS services
      },
      // IAM PassRole permission
      {
        Effect = "Allow",
        Action = "iam:PassRole",
        Resource = var.cicd_iam_passrole_arns, # Scoped to specific IAM roles that tasks can assume
        Condition = {
          "StringEquals" = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
      // S3 permissions for frontend deployment (if applicable)
      {
        Sid    = "S3FrontendDeployment",
        Effect = "Allow",
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject",
          "s3:GetBucketLocation"
          // "s3:PutObjectAcl" // If objects need to be public-read
        ],
        Resource = var.cicd_frontend_s3_bucket_arns # List of bucket ARN and bucket ARN/*
      },
      // CloudFront invalidation (if applicable)
      {
        Sid    = "CloudFrontInvalidation",
        Effect = "Allow",
        Action = "cloudfront:CreateInvalidation",
        Resource = var.cicd_cloudfront_distribution_arns
      }
      // Terraform state S3 & DynamoDB access has been REMOVED from this policy.
    ]
  })
  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "cicd_attach_permissions" {
  role       = aws_iam_role.cicd_github_actions.name
  policy_arn = aws_iam_policy.cicd_permissions.arn
}

# WARNING: The OIDC provider is a global, one-time setup per AWS account.
# This resource definition will cause an error if the provider already exists.
# It's recommended to create this manually once, or manage it via a separate, dedicated
# Terraform configuration for foundational resources. Ensure the thumbprint is current.
# For dynamic thumbprint fetching, consider using the 'tls' provider as commented below.
# data "tls_certificate" "github_oidc" { url = "https://token.actions.githubusercontent.com" }
# thumbprint_list = [data.tls_certificate.github_oidc.certificates[0].sha1_fingerprint]
resource "aws_iam_openid_connect_provider" "github_oidc_provider" {
  # This resource is defined here to ensure the OIDC trust relationship for the CI/CD role can be established.
  # Ideally, manage this globally ONCE per AWS account.
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  # Fetch thumbprints dynamically to avoid hardcoding and ensure they are up-to-date.
  # This requires the 'tls' provider.
  # provider "tls" {} # Would need to be configured at root level or here.
  # data "tls_certificate" "github_oidc" {
  #   url = "https://token.actions.githubusercontent.com"
  # }
  # thumbprint_list = [data.tls_certificate.github_oidc.certificates[0].sha1_fingerprint]
  # For now, using a known common thumbprint, but dynamic lookup is preferred.
  thumbprint_list = ["1c06332e3488478246566352a09a305897b855a0"] # Replace/verify with current GitHub OIDC thumbprint
                                                                # Often it's a list of more than one.
                                                                # The AWS console provides current required thumbprints when setting up manually.
  tags = var.common_tags

  # To prevent errors if this module is run when the OIDC provider already exists,
  # it's best to:
  # 1. Create it manually once.
  # 2. Or, use a separate Terraform configuration for one-time global resources.
  # 3. Or, use `terraform import` if it was created manually and you want to manage it via TF.
  # For this module, we include it for completeness of OIDC setup for the role,
  # but acknowledge it's a global, one-time resource.
}
