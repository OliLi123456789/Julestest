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

# --- IAM Policy for CI/CD Role ---
resource "aws_iam_policy" "cicd_permissions" {
  name        = "CICDPermissionsPolicy"
  description = "Policy for CI/CD role to manage infrastructure and deploy applications."
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      # Terraform state S3 bucket access
      {
        Effect = "Allow",
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ],
        Resource = [
          "arn:aws:s3:::${var.terraform_state_bucket_name}",
          "arn:aws:s3:::${var.terraform_state_bucket_name}/*"
        ]
      },
      # Terraform state DynamoDB lock table access
      {
        Effect = "Allow",
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ],
        Resource = "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${var.terraform_state_lock_table_name}"
      },
      # Broad permissions for Terraform to manage resources (scope down in production)
      {
        Effect = "Allow",
        Action = [
          "ec2:*", "rds:*", "eks:*", "ecs:*", "s3:*", "elasticloadbalancing:*",
          "autoscaling:*", "cloudwatch:*", "logs:*",
          "iam:PassRole", "iam:GetRole", "iam:CreateRole", "iam:DeleteRole",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
          "secretsmanager:GetSecretValue", "kms:Decrypt"
          # Add other service permissions as needed by Terraform
        ],
        Resource = "*" # WARNING: Highly permissive. Scope down in a real setup.
      },
      # ECR permissions to push/pull Docker images
      {
        Effect = "Allow",
        Action = [
            "ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
            "ecr:GetRepositoryPolicy", "ecr:DescribeRepositories", "ecr:ListImages", "ecr:DescribeImages",
            "ecr:BatchGetImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
            "ecr:CompleteLayerUpload", "ecr:PutImage"
        ],
        Resource = "*" # Can be scoped to specific ECR repositories
      }
    ]
  })
  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "cicd_attach_permissions" {
  role       = aws_iam_role.cicd_github_actions.name
  policy_arn = aws_iam_policy.cicd_permissions.arn
}

data "aws_iam_policy_document" "self_manage_oidc_provider" {
  # Policy allowing the CI/CD role to manage the OIDC provider itself if needed
  # This is optional and depends on how the OIDC provider is managed.
  # If OIDC provider is managed manually or by another process, this is not needed.
  statement {
    actions = [
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviders",
      "iam:TagOpenIDConnectProvider", # If using tags on the OIDC provider
      "iam:UntagOpenIDConnectProvider"
    ]
    resources = ["arn:aws:iam::${var.aws_account_id}:oidc-provider/*"] # Broad, but necessary for creation
  }
}

resource "aws_iam_policy" "self_manage_oidc_provider_policy" {
  name        = "SelfManageOIDCProviderPolicy"
  description = "Allows management of IAM OIDC providers. Attach to a role that sets up initial OIDC."
  policy      = data.aws_iam_policy_document.self_manage_oidc_provider.json
  tags        = var.common_tags
}

# It's better to attach this policy to a more privileged role used for initial setup,
# or manage the OIDC provider manually/separately.
# For this exercise, we'll assume the CI/CD role might need to ensure it exists.
# However, creating a global resource like an OIDC provider in a reusable module can be tricky.
# A data source to check for existing provider is safer.

data "aws_iam_openid_connect_provider" "github_oidc_existing" {
  # Attempt to fetch an existing OIDC provider for GitHub Actions.
  # This avoids trying to create it if it already exists, which would cause an error.
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github_oidc_provider" {
  # Create the OIDC provider only if it doesn't exist.
  # This requires a mechanism to check for existence, which `data` source does.
  # A more robust way is to use `count` based on whether `data.aws_iam_openid_connect_provider.github_oidc_existing.arn` is null or empty.
  # However, direct null checks on data source attributes are not straightforward.
  # For simplicity, this will attempt to create it. If it fails because it exists,
  # subsequent runs might succeed if the data source then picks it up, or it needs manual import/separate management.
  # A common pattern is to manage this OIDC provider as a one-time setup outside of frequently run modules.

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
