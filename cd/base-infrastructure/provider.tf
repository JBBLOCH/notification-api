provider "aws" {
  region = "us-east-2"

  assume_role {
    role_arn     = var.deploy_role
  }
}

terraform {
  backend "s3" {
    bucket = "terraform-notification-test"
    key    = "notification-test.tfstate"
    region = "us-east-2"
    encrypt = true
  }
}