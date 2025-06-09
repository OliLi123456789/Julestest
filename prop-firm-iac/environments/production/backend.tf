# environments/production/backend.tf

terraform {
  backend "s3" {
    bucket         = "prop-firm-terraform-state-<YOUR_AWS_ACCOUNT_ID>-<YOUR_REGION>" # REPLACE with your actual bucket name (should be same as staging)
    key            = "environments/production/terraform.tfstate"                     # Key is different for production
    region         = "<YOUR_REGION>"                                                 # REPLACE with your actual region (should be same as staging)
    dynamodb_table = "prop-firm-terraform-state-lock"                                # REPLACE with your actual DynamoDB table name (should be same as staging)
    encrypt        = true
  }
}
